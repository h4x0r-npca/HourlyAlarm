import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import time
import datetime
import os
import sys
import platform
import plistlib
import json
import queue
import subprocess
import tempfile
from pathlib import Path

import pygame
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
APP_NAME = "HourlyAlarm"
LAUNCH_AGENT_LABEL = "com.kyo.hourlyalarm"

ctk.set_appearance_mode("system")
ctk.set_default_color_theme("blue")

if IS_WINDOWS:
    import ctypes
    import pystray
    import win32com.client
    from winotify import Notification, audio
else:
    ctypes = None
    pystray = None
    win32com = None
    Notification = None
    audio = None

if IS_MACOS:
    try:
        import objc
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
            NSApplicationActivationPolicyRegular,
            NSEventMaskLeftMouseUp,
            NSEventMaskRightMouseUp,
            NSEventModifierFlagControl,
            NSEventTypeRightMouseUp,
            NSImage,
            NSMakeSize,
            NSMenu,
            NSMenuItem,
            NSStatusBar,
            NSVariableStatusItemLength,
        )
        from Foundation import NSObject
        from UserNotifications import (
            UNAuthorizationOptionAlert,
            UNAuthorizationOptionBadge,
            UNAuthorizationOptionSound,
            UNAuthorizationStatusAuthorized,
            UNAuthorizationStatusDenied,
            UNAuthorizationStatusNotDetermined,
            UNAuthorizationStatusProvisional,
            UNAlertStyleBanner,
            UNAlertStyleNone,
            UNMutableNotificationContent,
            UNNotificationPresentationOptionBanner,
            UNNotificationPresentationOptionList,
            UNNotificationRequest,
            UNUserNotificationCenter,
        )
    except Exception as e:
        print(f"macOS 메뉴바 초기화 모듈 로드 오류: {e}")
        objc = None
        NSObject = None
else:
    objc = None
    NSObject = None


if IS_MACOS and NSObject is not None:
    class MacStatusBarController(NSObject):
        def initWithApp_(self, app):
            self = objc.super(MacStatusBarController, self).init()
            if self is None:
                return None

            self.app = app
            self.status_item = None
            self.menu = None
            self._build_status_item()
            return self

        def _build_status_item(self):
            self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
            self.menu = NSMenu.alloc().init()

            show_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("화면보기", "showWindow:", "")
            show_item.setTarget_(self)
            self.menu.addItem_(show_item)

            quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("종료", "quitApp:", "")
            quit_item.setTarget_(self)
            self.menu.addItem_(quit_item)

            button = self.status_item.button()
            if button is None:
                return

            image = NSImage.alloc().initWithContentsOfFile_(self.app.macos_status_icon_path())
            if image:
                image.setSize_(NSMakeSize(18, 18))
                button.setImage_(image)
            else:
                button.setTitle_("⏰")

            button.setTarget_(self)
            button.setAction_("statusItemClicked:")
            button.sendActionOn_(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)

        def statusItemClicked_(self, sender):
            event = NSApplication.sharedApplication().currentEvent()
            if event is None:
                return

            is_right_click = event.type() == NSEventTypeRightMouseUp
            is_control_click = bool(event.modifierFlags() & NSEventModifierFlagControl)
            if is_right_click or is_control_click:
                self.status_item.popUpStatusItemMenu_(self.menu)
            elif event.clickCount() >= 2:
                self.app.show_window()

        def showWindow_(self, sender):
            self.app.show_window()

        def quitApp_(self, sender):
            self.app.quit_app()

        def stop(self):
            if self.status_item is not None:
                NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
                self.status_item = None


    class MacNotificationDelegate(NSObject):
        def userNotificationCenter_willPresentNotification_withCompletionHandler_(self, center, notification, completionHandler):
            completionHandler(UNNotificationPresentationOptionBanner | UNNotificationPresentationOptionList)
else:
    MacStatusBarController = None
    MacNotificationDelegate = None

def resource_path(rel_path: str) -> str:
    import sys, os
    if hasattr(sys, "_MEIPASS"):  # PyInstaller onefile 임시폴더
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)


class HourlyAlarmApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("시간 알리미")
        self.root.geometry("720x760")
        self.root.minsize(640, 680)
        self.root.resizable(True, True)
        self.ui_font = "맑은 고딕" if IS_WINDOWS else "AppleGothic" if IS_MACOS else "TkDefaultFont"

        # ===== 상태 변수 =====
        self.default_sound_file = resource_path("Ring10.wav")
        self.default_half_hour_sound_file = resource_path("love-emote-animal-crossing.mp3")
        settings = self._load_settings()

        self.alarm_enabled_value = bool(settings.get("hourly_enabled", True))
        self.half_hour_alarm_enabled_value = bool(settings.get("half_hour_enabled", True))
        self.alarm_enabled = tk.BooleanVar(value=self.alarm_enabled_value)
        self.half_hour_alarm_enabled = tk.BooleanVar(value=self.half_hour_alarm_enabled_value)
        self.autostart_enabled = tk.BooleanVar(value=False)

        # 각 알림은 서로 다른 음원을 사용할 수 있습니다.
        self.sound_file = self._valid_saved_sound(settings.get("hourly_sound"), self.default_sound_file)
        self.half_hour_sound_file = self._valid_saved_sound(
            settings.get("half_hour_sound"), self.default_half_hour_sound_file
        )

        self.running = True
        self.alarm_thread = None
        self.tray_icon = None
        self.tray_available = (IS_WINDOWS and pystray is not None) or (IS_MACOS and MacStatusBarController is not None)
        self._tray_thread_started = False
        self.status_bar_controller = None
        self.notification_center = None
        self.notification_delegate = None
        self.notification_prompt_queue = queue.Queue()
        self.notification_prompt_shown = False
        self.audio_ready = False

        # pygame 초기화
        try:
            pygame.mixer.init()
            self.audio_ready = True
        except Exception as e:
            print(f"오디오 초기화 오류: {e}")

        # 자동 시작 상태 확인
        self.check_autostart_status()

        # Windows에서는 트레이, macOS에서는 메뉴바 상태 아이콘을 사용
        if IS_MACOS:
            self._set_macos_dock_visible(True)
            self._configure_macos_reopen()

        if self.tray_available:
            self.create_tray_icon()
            self._ensure_tray_running()

        # GUI 구성
        self.setup_gui()

        # 창 아이콘(제목표시줄) 적용
        self._apply_window_icon()

        # 작업표시줄 아이콘(AppID + .ico) 적용
        self._apply_appid_and_taskbar_icon()

        # 알람 스레드 시작
        self.start_alarm_thread()

        # X버튼 → 종료 대신 트레이로 숨김
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Windows 트레이가 있을 때만 시작 시 숨김
        if IS_WINDOWS and self.tray_available:
            self.root.after(100, self.start_minimized_to_tray)

        if IS_MACOS:
            self.root.after(300, self._process_notification_prompt_queue)
            self.root.after(700, self._configure_macos_notifications)

    def _settings_path(self):
        if IS_WINDOWS:
            base_dir = Path(os.getenv("APPDATA", Path.home()))
        elif IS_MACOS:
            base_dir = Path.home() / "Library" / "Application Support"
        else:
            base_dir = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
        return base_dir / APP_NAME / "settings.json"

    def _load_settings(self):
        try:
            with self._settings_path().open("r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save_settings(self):
        data = {
            "hourly_enabled": self.alarm_enabled_value,
            "half_hour_enabled": self.half_hour_alarm_enabled_value,
            "hourly_sound": self.sound_file,
            "half_hour_sound": self.half_hour_sound_file,
        }
        try:
            path = self._settings_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as fp:
                json.dump(data, fp, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"설정 저장 오류: {e}")

    @staticmethod
    def _valid_saved_sound(saved_path, default_path):
        if saved_path and os.path.isfile(saved_path):
            return saved_path
        return default_path

    # ================= GUI =================
    def setup_gui(self):
        self.root.configure(fg_color=("#eef3f8", "#0b1118"))
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        main_frame = ctk.CTkScrollableFrame(self.root, fg_color="transparent", corner_radius=0)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        main_frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(main_frame, fg_color=("#176bcb", "#155aa7"), corner_radius=20)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="시간 알리미", text_color="white",
            font=ctk.CTkFont(family=self.ui_font, size=26, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(22, 2))
        ctk.CTkLabel(
            header, text="매 시각과 30분을 원하는 소리로 알려드려요.", text_color="#dcecff",
            font=ctk.CTkFont(family=self.ui_font, size=13)
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 22))

        self._create_alarm_card(
            main_frame, row=1, title="정각 알림", subtitle="매 시간 00분에 알림",
            variable=self.alarm_enabled, toggle_command=self.toggle_alarm,
            sound_kind="hourly"
        )
        self._create_alarm_card(
            main_frame, row=2, title="30분 알림", subtitle="매 시간 30분에 알림",
            variable=self.half_hour_alarm_enabled, toggle_command=self.toggle_half_hour_alarm,
            sound_kind="half_hour"
        )

        settings_card = ctk.CTkFrame(main_frame, corner_radius=18, fg_color=("#ffffff", "#151e29"))
        settings_card.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        settings_card.grid_columnconfigure(0, weight=1)
        autostart_text = "Mac 로그인 시 자동 실행" if IS_MACOS else "컴퓨터 시작 시 자동 실행"
        ctk.CTkLabel(
            settings_card, text="시작 설정", anchor="w",
            font=ctk.CTkFont(family=self.ui_font, size=16, weight="bold")
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 2))
        ctk.CTkLabel(
            settings_card, text="백그라운드에서 알림을 놓치지 않도록 실행합니다.", anchor="w",
            text_color=("#667085", "#9aa7b6"), font=ctk.CTkFont(family=self.ui_font, size=12)
        ).grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 14))
        ctk.CTkSwitch(
            settings_card, text=autostart_text, variable=self.autostart_enabled,
            command=self.toggle_autostart, font=ctk.CTkFont(family=self.ui_font, size=13)
        ).grid(row=2, column=0, sticky="w", padx=20, pady=(0, 18))

        clock_card = ctk.CTkFrame(main_frame, corner_radius=18, fg_color=("#ffffff", "#151e29"))
        clock_card.grid(row=4, column=0, sticky="ew", pady=(0, 14))
        clock_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            clock_card, text="현재 시간", text_color=("#667085", "#9aa7b6"),
            font=ctk.CTkFont(family=self.ui_font, size=12)
        ).grid(row=0, column=0, pady=(16, 0))
        self.current_time_label = ctk.CTkLabel(
            clock_card, text="", font=ctk.CTkFont(family=self.ui_font, size=21, weight="bold")
        )
        self.current_time_label.grid(row=1, column=0, pady=(2, 4))
        self.status_label = ctk.CTkLabel(
            clock_card, text="알림 설정이 준비되었습니다.", text_color=("#176bcb", "#65a8ff"),
            font=ctk.CTkFont(family=self.ui_font, size=12)
        )
        self.status_label.grid(row=2, column=0, pady=(0, 16))

        minimize_text = "시스템 트레이로 최소화" if IS_WINDOWS and self.tray_available else "창 숨기기"
        ctk.CTkButton(
            main_frame, text=minimize_text, height=44, corner_radius=12,
            command=self.minimize_to_tray, font=ctk.CTkFont(family=self.ui_font, size=14, weight="bold")
        ).grid(row=5, column=0, sticky="ew")
        ctk.CTkLabel(
            main_frame, text="Kyo · dersertfox@kakao.com", text_color=("#7b8794", "#718096"),
            font=ctk.CTkFont(family=self.ui_font, size=10)
        ).grid(row=6, column=0, pady=(12, 2))

        self._update_sound_label()

        self.update_time_display()

    def _create_alarm_card(self, parent, row, title, subtitle, variable, toggle_command, sound_kind):
        card = ctk.CTkFrame(parent, corner_radius=18, fg_color=("#ffffff", "#151e29"))
        card.grid(row=row, column=0, sticky="ew", pady=(0, 14))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card, text=title, anchor="w", font=ctk.CTkFont(family=self.ui_font, size=18, weight="bold")
        ).grid(row=0, column=0, sticky="ew", padx=(20, 8), pady=(18, 1))
        ctk.CTkSwitch(card, text="", variable=variable, command=toggle_command, width=48).grid(
            row=0, column=1, padx=(8, 20), pady=(18, 1)
        )
        ctk.CTkLabel(
            card, text=subtitle, anchor="w", text_color=("#667085", "#9aa7b6"),
            font=ctk.CTkFont(family=self.ui_font, size=12)
        ).grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 12))

        sound_box = ctk.CTkFrame(card, fg_color=("#f1f5f9", "#202b38"), corner_radius=10)
        sound_box.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 12))
        sound_box.grid_columnconfigure(0, weight=1)
        label = ctk.CTkLabel(
            sound_box, text="", anchor="w", text_color=("#344054", "#d0d8e2"),
            font=ctk.CTkFont(family=self.ui_font, size=12)
        )
        label.grid(row=0, column=0, sticky="ew", padx=13, pady=10)
        if sound_kind == "hourly":
            self.sound_file_label = label
        else:
            self.half_hour_sound_file_label = label

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 18))
        for column in range(3):
            buttons.grid_columnconfigure(column, weight=1, uniform="sound")
        ctk.CTkButton(
            buttons, text="소리 변경", height=34, corner_radius=9,
            command=lambda: self.change_sound_file(sound_kind)
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            buttons, text="미리 듣기", height=34, corner_radius=9,
            fg_color=("#e5edf6", "#29384a"), hover_color=("#d4e1ef", "#34475d"),
            text_color=("#1f4f7a", "#d9e9fa"), command=lambda: self.test_sound(sound_kind)
        ).grid(row=0, column=1, sticky="ew", padx=4)
        ctk.CTkButton(
            buttons, text="기본음", height=34, corner_radius=9,
            fg_color=("#e5edf6", "#29384a"), hover_color=("#d4e1ef", "#34475d"),
            text_color=("#1f4f7a", "#d9e9fa"), command=lambda: self.reset_to_default_sound(sound_kind)
        ).grid(row=0, column=2, sticky="ew", padx=(4, 0))

    def update_time_display(self):
        self.current_time_label.configure(text=datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        self.root.after(1000, self.update_time_display)

    def _apply_window_icon(self):
        """제목표시줄 아이콘을 시계 아이콘으로"""
        try:
            pil_img = self._make_clock_icon(32)
            self._tk_icon = ImageTk.PhotoImage(pil_img)  # GC 방지 위해 self에 보관
            self.root.iconphoto(True, self._tk_icon)
        except Exception:
            pass

    # ================= 토글/설정 =================
    def toggle_alarm(self):
        self.alarm_enabled_value = self.alarm_enabled.get()
        self._save_settings()
        state = "켜졌습니다" if self.alarm_enabled_value else "꺼졌습니다"
        self._set_status(f"정각 알림이 {state}.")

    def toggle_half_hour_alarm(self):
        self.half_hour_alarm_enabled_value = self.half_hour_alarm_enabled.get()
        self._save_settings()
        state = "켜졌습니다" if self.half_hour_alarm_enabled_value else "꺼졌습니다"
        self._set_status(f"30분 알림이 {state}.")

    def _set_status(self, message):
        try:
            self.status_label.configure(text=message)
        except (AttributeError, tk.TclError):
            pass

    def toggle_autostart(self):
        if self.autostart_enabled.get():
            if self.add_to_startup():
                self._set_status("자동 실행이 켜졌습니다.")
            else:
                self.autostart_enabled.set(False)
                messagebox.showerror("오류", "시작 프로그램 등록에 실패했습니다.")
        else:
            if self.remove_from_startup():
                self._set_status("자동 실행이 꺼졌습니다.")
            else:
                self.autostart_enabled.set(True)
                messagebox.showerror("오류", "시작 프로그램 제거에 실패했습니다.")

    def check_autostart_status(self):
        try:
            if IS_WINDOWS:
                startup_folder = os.path.join(os.getenv('APPDATA'), r'Microsoft\Windows\Start Menu\Programs\Startup')
                self.autostart_enabled.set(os.path.exists(os.path.join(startup_folder, "HourlyAlarm.lnk")))
            elif IS_MACOS:
                self.autostart_enabled.set(self._launch_agent_path().exists())
            else:
                self.autostart_enabled.set(False)
        except Exception as e:
            print(f"자동 시작 상태 확인 오류: {e}")

    def add_to_startup(self):
        try:
            if IS_MACOS:
                return self._add_macos_launch_agent()
            if not IS_WINDOWS:
                return False

            startup_folder = os.path.join(os.getenv('APPDATA'), r'Microsoft\Windows\Start Menu\Programs\Startup')
            os.makedirs(startup_folder, exist_ok=True)
            shortcut_path = os.path.join(startup_folder, "HourlyAlarm.lnk")
            target_path = os.path.abspath(sys.argv[0])
            working_dir = os.path.dirname(target_path)
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.TargetPath = target_path
            shortcut.WorkingDirectory = working_dir
            shortcut.Description = "정각 및 30분 시간 알림 프로그램"
            shortcut.save()
            return True
        except Exception as e:
            print(f"시작 프로그램 추가 오류: {e}")
            return False

    def remove_from_startup(self):
        try:
            if IS_MACOS:
                return self._remove_macos_launch_agent()
            if not IS_WINDOWS:
                return False

            startup_folder = os.path.join(os.getenv('APPDATA'), r'Microsoft\Windows\Start Menu\Programs\Startup')
            shortcut_path = os.path.join(startup_folder, "HourlyAlarm.lnk")
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
            return True
        except Exception as e:
            print(f"시작 프로그램 제거 오류: {e}")
            return False

    def _launch_agent_path(self):
        return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"

    def _find_app_bundle(self):
        exe_path = Path(sys.executable).resolve()
        for path in [exe_path, *exe_path.parents]:
            if path.suffix == ".app":
                return path
        return None

    def _macos_program_arguments(self):
        app_bundle = self._find_app_bundle()
        if app_bundle:
            return ["/usr/bin/open", str(app_bundle)]

        script_path = Path(sys.argv[0]).resolve()
        return [sys.executable, str(script_path)]

    def _refresh_launch_agent(self, plist_path):
        gui_target = f"gui/{os.getuid()}"
        subprocess.run(
            ["launchctl", "bootout", gui_target, str(plist_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        result = subprocess.run(
            ["launchctl", "bootstrap", gui_target, str(plist_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            subprocess.run(
                ["launchctl", "load", str(plist_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    def _add_macos_launch_agent(self):
        plist_path = self._launch_agent_path()
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist = {
            "Label": LAUNCH_AGENT_LABEL,
            "ProgramArguments": self._macos_program_arguments(),
            "RunAtLoad": True,
            "StandardOutPath": f"/tmp/{LAUNCH_AGENT_LABEL}.out.log",
            "StandardErrorPath": f"/tmp/{LAUNCH_AGENT_LABEL}.err.log",
        }
        with plist_path.open("wb") as fp:
            plistlib.dump(plist, fp)
        self._refresh_launch_agent(plist_path)
        return True

    def _remove_macos_launch_agent(self):
        plist_path = self._launch_agent_path()
        gui_target = f"gui/{os.getuid()}"
        subprocess.run(
            ["launchctl", "bootout", gui_target, str(plist_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if plist_path.exists():
            plist_path.unlink()
        return True

    # ================= 사운드/알림 =================
    def _update_sound_label(self):
        """정각/30분 알림의 현재 음원 이름을 갱신합니다."""
        try:
            hourly_name = os.path.basename(self.sound_file)
            if os.path.abspath(self.sound_file) == os.path.abspath(self.default_sound_file):
                hourly_name += "  ·  기본음"
            half_hour_name = os.path.basename(self.half_hour_sound_file)
            if os.path.abspath(self.half_hour_sound_file) == os.path.abspath(self.default_half_hour_sound_file):
                half_hour_name += "  ·  기본음"
            self.sound_file_label.configure(text=f"♪  {hourly_name}")
            self.half_hour_sound_file_label.configure(text=f"♪  {half_hour_name}")
        except (AttributeError, tk.TclError):
            pass

    def change_sound_file(self, sound_kind="hourly"):
        alarm_name = "30분" if sound_kind == "half_hour" else "정각"
        filename = filedialog.askopenfilename(
            title=f"{alarm_name} 알림 사운드 선택",
            filetypes=[("오디오 파일", "*.wav *.mp3 *.ogg"),
                       ("WAV 파일", "*.wav"),
                       ("MP3 파일", "*.mp3"),
                       ("OGG 파일", "*.ogg"),
                       ("모든 파일", "*.*")]
        )
        if filename:
            if sound_kind == "half_hour":
                self.half_hour_sound_file = filename
            else:
                self.sound_file = filename
            self._update_sound_label()
            self._save_settings()
            self._set_status(f"{alarm_name} 알림 소리를 변경했습니다.")

    def reset_to_default_sound(self, sound_kind="hourly"):
        if sound_kind == "half_hour":
            self.half_hour_sound_file = self.default_half_hour_sound_file
            alarm_name = "30분"
        else:
            self.sound_file = self.default_sound_file
            alarm_name = "정각"
        self._update_sound_label()
        self._save_settings()
        self._set_status(f"{alarm_name} 알림 소리를 기본음으로 바꿨습니다.")

    def test_sound(self, sound_kind="hourly"):
        sound_file = self.half_hour_sound_file if sound_kind == "half_hour" else self.sound_file
        alarm_name = "30분" if sound_kind == "half_hour" else "정각"
        if not os.path.exists(sound_file):
            messagebox.showerror("오류", "사운드 파일을 찾을 수 없습니다.")
            return
        if not self.audio_ready:
            messagebox.showerror("오류", "오디오 장치를 초기화하지 못했습니다.")
            return
        try:
            pygame.mixer.music.load(sound_file)
            pygame.mixer.music.play()
            self._set_status(f"{alarm_name} 알림 소리를 재생하고 있습니다.")
        except Exception as e:
            messagebox.showerror("오류", f"사운드 재생 실패: {e}")

    def play_alarm(self, sound_file):
        try:
            if self.audio_ready and os.path.exists(sound_file):
                pygame.mixer.music.load(sound_file)
                pygame.mixer.music.play()
        except Exception as e:
            print(f"알람 재생 오류: {e}")

    def show_toast_notification(self, hour, sound_kind="hourly"):
        try:
            is_half_hour = sound_kind == "half_hour"
            title = "30분 알림" if is_half_hour else "정각 알림"
            message = f"{hour}시 30분입니다" if is_half_hour else f"{hour}시 정각입니다"
            if IS_WINDOWS:
                toast = Notification(app_id="시간 알리미", title=f"⏰ {title}", msg=message, duration="short")
                toast.set_audio(audio.Default, loop=False)
                toast.show()
            elif IS_MACOS:
                self._show_macos_notification(title, message)
            else:
                print(f"{title}: {message}")
        except Exception as e:
            print(f"토스트 알림 오류: {e}")

    def _apple_script_string(self, value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _configure_macos_notifications(self):
        if not IS_MACOS or MacNotificationDelegate is None:
            return

        try:
            self.notification_center = UNUserNotificationCenter.currentNotificationCenter()
            self.notification_delegate = MacNotificationDelegate.alloc().init()
            self.notification_center.setDelegate_(self.notification_delegate)
            self.notification_center.getNotificationSettingsWithCompletionHandler_(
                self._handle_macos_notification_settings
            )
        except Exception as e:
            print(f"macOS 알림 초기화 오류: {e}")

    def _handle_macos_notification_settings(self, settings):
        try:
            status = settings.authorizationStatus()
            alert_style = settings.alertStyle()
            self.notification_prompt_queue.put(("settings", status, alert_style))
        except Exception as e:
            print(f"macOS 알림 상태 확인 오류: {e}")

    def _process_notification_prompt_queue(self):
        try:
            while True:
                item = self.notification_prompt_queue.get_nowait()
                if not item:
                    continue

                if item[0] == "settings":
                    _, status, alert_style = item
                    self._handle_macos_notification_status_on_main(status, alert_style)
                elif item[0] == "authorization_result":
                    _, granted, error = item
                    self._handle_macos_authorization_result_on_main(granted, error)
        except queue.Empty:
            pass

        if self.running:
            self.root.after(500, self._process_notification_prompt_queue)

    def _handle_macos_notification_status_on_main(self, status, alert_style):
        if self.notification_prompt_shown:
            return

        if status == UNAuthorizationStatusNotDetermined:
            self.notification_prompt_shown = True
            allow = messagebox.askyesno(
                "알림 권한 필요",
                "시간 알림을 화면 오른쪽 상단 배너로 표시하려면 macOS 알림 권한이 필요합니다.\n\n지금 알림을 허용하시겠습니까?"
            )
            if allow:
                self._request_macos_notification_authorization()
            return

        if status == UNAuthorizationStatusDenied:
            self.notification_prompt_shown = True
            self._ask_open_macos_notification_settings(
                "현재 HourlyAlarm 알림이 macOS에서 거부되어 있습니다.\n\n알림 설정을 열어서 알림 허용을 켜시겠습니까?"
            )
            return

        allowed_statuses = (UNAuthorizationStatusAuthorized, UNAuthorizationStatusProvisional)
        if status in allowed_statuses and alert_style != UNAlertStyleBanner:
            self.notification_prompt_shown = True
            self._ask_open_macos_notification_settings(
                "HourlyAlarm 알림 권한은 있지만 배너 표시가 켜져 있지 않습니다.\n\n알림 설정을 열어서 배너 표시를 켜시겠습니까?"
            )

    def _request_macos_notification_authorization(self):
        if self.notification_center is None:
            return

        options = UNAuthorizationOptionAlert | UNAuthorizationOptionSound | UNAuthorizationOptionBadge
        self.notification_center.requestAuthorizationWithOptions_completionHandler_(
            options,
            lambda granted, error: self.notification_prompt_queue.put(("authorization_result", granted, error)),
        )

    def _handle_macos_authorization_result_on_main(self, granted, error):
        if error:
            print(f"macOS 알림 권한 오류: {error}")
            self._ask_open_macos_notification_settings(
                "알림 권한 요청 중 오류가 발생했습니다.\n\nmacOS 알림 설정을 열어 직접 확인하시겠습니까?"
            )
            return

        if granted:
            self.notification_prompt_shown = False
            self.notification_center.getNotificationSettingsWithCompletionHandler_(
                self._handle_macos_notification_settings
            )
        else:
            self._ask_open_macos_notification_settings(
                "알림 권한이 허용되지 않았습니다.\n\nmacOS 알림 설정을 열어서 직접 허용하시겠습니까?"
            )

    def _ask_open_macos_notification_settings(self, message):
        if messagebox.askyesno("알림 설정 확인", message):
            self._open_macos_notification_settings()

    def _open_macos_notification_settings(self):
        urls = [
            f"x-apple.systempreferences:com.apple.Notifications-Settings.extension?id={LAUNCH_AGENT_LABEL}",
            "x-apple.systempreferences:com.apple.Notifications-Settings.extension",
        ]
        for url in urls:
            result = subprocess.run(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if result.returncode == 0:
                break

    def _show_macos_notification(self, title, message):
        if self.notification_center is None:
            script = (
                f"display notification {self._apple_script_string(message)} "
                f"with title {self._apple_script_string(title)}"
            )
            subprocess.run(["osascript", "-e", script], check=False)
            return

        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(message)

        identifier = f"time-alarm-{datetime.datetime.now().timestamp()}"
        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(identifier, content, None)
        self.notification_center.addNotificationRequest_withCompletionHandler_(
            request,
            lambda error: print(f"macOS 알림 표시 오류: {error}") if error else None,
        )

    # ================= 알람 스레드 =================
    def alarm_worker(self):
        last_trigger = None
        while self.running:
            now = datetime.datetime.now()
            trigger_key = (now.date(), now.hour, now.minute)
            sound_kind = None
            sound_file = None

            if now.minute == 0 and self.alarm_enabled_value:
                sound_kind = "hourly"
                sound_file = self.sound_file
            elif now.minute == 30 and self.half_hour_alarm_enabled_value:
                sound_kind = "half_hour"
                sound_file = self.half_hour_sound_file

            # 2초의 여유를 두어 시스템 부하로 00초를 한 번 건너뛰어도 울리게 합니다.
            if sound_kind and now.second < 2 and trigger_key != last_trigger:
                self.play_alarm(sound_file)
                self.show_toast_notification(now.hour, sound_kind)
                last_trigger = trigger_key
            time.sleep(0.5)

    def start_alarm_thread(self):
        self.alarm_thread = threading.Thread(target=self.alarm_worker, daemon=True)
        self.alarm_thread.start()

    # ================= 트레이 아이콘/아이콘 적용 =================
    def _make_clock_icon(self, size=64):
        """시계 모양 아이콘 생성 (숨겨진 아이콘 영역/트레이 공통)"""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # 시계 판
        d.ellipse((3, 3, size - 3, size - 3), fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=3)

        # 눈금 (12, 3, 6, 9 방향)
        import math
        cx = cy = size // 2
        for angle, w in [(0, 3), (90, 2), (180, 3), (270, 2)]:
            r1 = size * 0.38
            r2 = size * 0.46
            x1 = cx + r1 * math.cos(math.radians(angle))
            y1 = cy + r1 * math.sin(math.radians(angle))
            x2 = cx + r2 * math.cos(math.radians(angle))
            y2 = cy + r2 * math.sin(math.radians(angle))
            d.line((x1, y1, x2, y2), fill=(0, 0, 0, 255), width=w)

        # 시침/분침 (12:10)
        d.line((cx, cy, cx, cy - size * 0.17), fill=(0, 0, 0, 255), width=5)      # 시침
        d.line((cx, cy, cx + size * 0.20, cy), fill=(0, 0, 0, 255), width=4)      # 분침

        # 축
        d.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(0, 0, 0, 255))
        return img

    def _apply_appid_and_taskbar_icon(self):
        """
        작업표시줄 아이콘 기본 파이썬 아이콘 문제 해결:
        - AppUserModelID 명시(독립 앱으로 인식)
        - .ico 파일 생성 및 iconbitmap 지정
        """
        if not IS_WINDOWS:
            return

        # AppID
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Kyo.HourlyAlarm")
        except Exception:
            pass

        # .ico 적용
        try:
            ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clock.ico")
            if not os.path.exists(ico_path):
                base = self._make_clock_icon(256)
                sizes = [16, 24, 32, 48, 64, 128, 256]
                imgs = [base.resize((s, s), Image.LANCZOS) for s in sizes]
                imgs[0].save(ico_path, format="ICO", sizes=[(s, s) for s in sizes])

            self.root.iconbitmap(ico_path)  # 작업표시줄/Alt+Tab/제목표시줄
            # 보조로 PhotoImage도 지정(HiDPI 강화)
            self._tk_icon = ImageTk.PhotoImage(self._make_clock_icon(32))
            self.root.iconphoto(True, self._tk_icon)
        except Exception as e:
            print(f"아이콘 적용 오류: {e}")

    def create_tray_icon(self):
        """Windows 트레이 또는 macOS 메뉴바 아이콘 생성 — 항상 유지"""
        if not self.tray_available:
            return

        if IS_MACOS:
            self.status_bar_controller = MacStatusBarController.alloc().initWithApp_(self)
            return

        image = self._make_clock_icon(64)
        menu = pystray.Menu(
            pystray.MenuItem("열기", self.show_window, default=True),  # 더블클릭 = 열기
            pystray.MenuItem("종료", self.quit_app)
        )
        self.tray_icon = pystray.Icon("hourly_alarm", image, "시간 알리미", menu)

    def _ensure_tray_running(self):
        """아이콘 런루프를 한 번만 실행"""
        if IS_MACOS:
            return

        if self.tray_available and self.tray_icon and not self._tray_thread_started:
            t = threading.Thread(target=self.tray_icon.run, daemon=True)
            t.start()
            self._tray_thread_started = True

    def minimize_to_tray(self):
        """창 숨김(종료 아님). Windows에서는 트레이 아이콘으로 복귀."""
        self.root.withdraw()
        if IS_MACOS:
            self._set_macos_dock_visible(False)
        self._ensure_tray_running()

    def start_minimized_to_tray(self):
        self.minimize_to_tray()

    def show_window(self, icon=None, item=None):
        """창 보이기 — 최상위로 노출"""
        self._ensure_tray_running()
        try:
            if IS_MACOS:
                self._set_macos_dock_visible(True)
            self.root.deiconify()
            self.root.state('normal')
            self.root.lift()
            if IS_MACOS:
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self.root.attributes('-topmost', True)
            self.root.update_idletasks()
            self.root.attributes('-topmost', False)
            self.root.focus_force()
        except Exception:
            pass

    def _configure_macos_reopen(self):
        try:
            self.root.createcommand("::tk::mac::ReopenApplication", self.show_window)
        except Exception:
            pass

    def _set_macos_dock_visible(self, visible):
        if not IS_MACOS or NSObject is None:
            return

        try:
            policy = NSApplicationActivationPolicyRegular if visible else NSApplicationActivationPolicyAccessory
            NSApplication.sharedApplication().setActivationPolicy_(policy)
        except Exception as e:
            print(f"macOS Dock 표시 상태 변경 오류: {e}")

    def macos_status_icon_path(self):
        icon_path = Path(tempfile.gettempdir()) / "hourlyalarm-status-icon.png"
        try:
            self._make_clock_icon(64).save(icon_path)
        except Exception:
            return ""
        return str(icon_path)

    def quit_app(self, icon=None, item=None):
        """종료(오직 트레이 메뉴에서만 호출)"""
        self.running = False
        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except Exception:
            pass
        try:
            if self.status_bar_controller:
                self.status_bar_controller.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def on_closing(self):
        """X 버튼: 종료하지 않고 트레이로 숨김"""
        self.minimize_to_tray()

    # ================= 앱 실행 =================
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = HourlyAlarmApp()
    app.run()
