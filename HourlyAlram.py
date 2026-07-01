import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
import datetime
import os
import sys
import platform
import plistlib
import queue
import subprocess
import tempfile
from pathlib import Path

import pygame
from PIL import Image, ImageDraw, ImageTk

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
APP_NAME = "HourlyAlarm"
LAUNCH_AGENT_LABEL = "com.kyo.hourlyalarm"

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
        self.root = tk.Tk()
        self.root.title("정각 알림 프로그램")
        if IS_MACOS:
            self.root.geometry("560x540")
            self.root.minsize(560, 540)
            self.root.resizable(True, True)
        else:
            self.root.geometry("380x450")
            self.root.resizable(False, False)
        self.ui_font = "맑은 고딕" if IS_WINDOWS else "AppleGothic" if IS_MACOS else "TkDefaultFont"

        # ===== 상태 변수 =====
        self.alarm_enabled = tk.BooleanVar(value=True)
        self.alarm_enabled_value = True
        self.autostart_enabled = tk.BooleanVar(value=False)

        # ★ 기본 알림음 경로 + 현재 사용 음원 경로
        self.default_sound_file = resource_path("Ring10.wav")
        self.sound_file = self.default_sound_file

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

    # ================= GUI =================
    def setup_gui(self):
        padding = "24" if IS_MACOS else "20"
        sound_wraplength = 500 if IS_MACOS else 330

        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        main_frame = ttk.Frame(self.root, padding=padding)
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        for column in range(3):
            main_frame.grid_columnconfigure(column, weight=1, uniform="main")

        title_label = ttk.Label(main_frame, text="⏰ 정각 알림 프로그램", font=(self.ui_font, 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))

        alarm_check = ttk.Checkbutton(
            main_frame, text="정각 알림 활성화",
            variable=self.alarm_enabled, command=self.toggle_alarm
        )
        alarm_check.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=10)

        autostart_text = "Mac 로그인 시 자동 실행" if IS_MACOS else "컴퓨터 시작 시 자동 실행"
        autostart_check = ttk.Checkbutton(
            main_frame, text=autostart_text,
            variable=self.autostart_enabled, command=self.toggle_autostart
        )
        autostart_check.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=10)

        separator1 = ttk.Separator(main_frame, orient='horizontal')
        separator1.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=15)

        sound_label = ttk.Label(main_frame, text="알림 사운드:", font=(self.ui_font, 10, "bold"))
        sound_label.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(0, 5))

        # 사운드 파일 표시(초기엔 '기본알림음'으로 표시)
        self.sound_file_label = ttk.Label(
            main_frame, text="", foreground="blue", wraplength=sound_wraplength, anchor="w", justify="left"
        )
        self.sound_file_label.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        self._update_sound_label()  # ★ 라벨 갱신

        # 버튼들
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, columnspan=3, pady=10, sticky=(tk.W, tk.E))

        ttk.Button(button_frame, text="사운드 변경", command=self.change_sound_file)\
            .grid(row=0, column=0, padx=5, sticky=(tk.W, tk.E))
        ttk.Button(button_frame, text="사운드 테스트", command=self.test_sound)\
            .grid(row=0, column=1, padx=5, sticky=(tk.W, tk.E))
        ttk.Button(button_frame, text="기본알림음으로 변경", command=self.reset_to_default_sound)\
            .grid(row=0, column=2, padx=5, sticky=(tk.W, tk.E))

        for column in range(3):
            button_frame.grid_columnconfigure(column, weight=1, uniform="sound_buttons")

        separator2 = ttk.Separator(main_frame, orient='horizontal')
        separator2.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=15)

        # ── 현재 시간 라인을 한 줄에 배치 (pack 사용)
        time_row = ttk.Frame(main_frame)
        time_row.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 0))

        lbl_now = ttk.Label(time_row, text="현재 시간:", font=(self.ui_font, 10))
        lbl_now.pack(side="left", padx=(0, 8))

        self.current_time_label = ttk.Label(
            time_row,
            text="",
            font=(self.ui_font, 12, "bold"),
            foreground="green",
            anchor="w",     # 라벨 내부 좌측 정렬
            justify="left"
        )
        self.current_time_label.pack(side="left")
        # 제작자 표기
        self.author_label = ttk.Label(
            main_frame,
            text="제작자  Kyo : dersertfox@kakao.com",
            font=(self.ui_font, 9),
            foreground="#6b7280"
        )
        self.author_label.grid(row=9, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))

        minimize_text = "시스템 트레이로 최소화" if IS_WINDOWS and self.tray_available else "창 숨기기"
        ttk.Button(main_frame, text=minimize_text, command=self.minimize_to_tray)\
            .grid(row=10, column=0, columnspan=3, pady=(20, 0), sticky=(tk.W, tk.E))

        self.update_time_display()

    def update_time_display(self):
        self.current_time_label.config(text=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
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
        if self.alarm_enabled_value:
            messagebox.showinfo("알림", "정각 알림이 활성화되었습니다.")
        else:
            messagebox.showinfo("알림", "정각 알림이 비활성화되었습니다.")

    def toggle_autostart(self):
        if self.autostart_enabled.get():
            if self.add_to_startup():
                messagebox.showinfo("성공", "시작 프로그램에 등록되었습니다.")
            else:
                self.autostart_enabled.set(False)
                messagebox.showerror("오류", "시작 프로그램 등록에 실패했습니다.")
        else:
            if self.remove_from_startup():
                messagebox.showinfo("성공", "시작 프로그램에서 제거되었습니다.")
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
            shortcut.Description = "정각 알림 프로그램"
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
        """사운드 라벨 텍스트 갱신: 기본알림음 또는 파일명만 표시"""
        try:
            if os.path.abspath(self.sound_file) == os.path.abspath(self.default_sound_file):
                name = "기본알림음"
            else:
                name = os.path.basename(self.sound_file)
            self.sound_file_label.config(text=name)
        except Exception:
            pass

    def change_sound_file(self):
        filename = filedialog.askopenfilename(
            title="알림 사운드 선택",
            filetypes=[("오디오 파일", "*.wav *.mp3 *.ogg"),
                       ("WAV 파일", "*.wav"),
                       ("MP3 파일", "*.mp3"),
                       ("OGG 파일", "*.ogg"),
                       ("모든 파일", "*.*")]
        )
        if filename:
            self.sound_file = filename
            self._update_sound_label()
            messagebox.showinfo("성공", "알림 사운드가 변경되었습니다.")

    def reset_to_default_sound(self):
        """기본알림음(Ring10.wav)으로 되돌리기"""
        self.sound_file = self.default_sound_file
        self._update_sound_label()
        messagebox.showinfo("완료", "알림 사운드가 기본알림음으로 변경되었습니다.")

    def test_sound(self):
        if not os.path.exists(self.sound_file):
            messagebox.showerror("오류", "사운드 파일을 찾을 수 없습니다.")
            return
        if not self.audio_ready:
            messagebox.showerror("오류", "오디오 장치를 초기화하지 못했습니다.")
            return
        try:
            pygame.mixer.music.load(self.sound_file)
            pygame.mixer.music.play()
        except Exception as e:
            messagebox.showerror("오류", f"사운드 재생 실패: {e}")

    def play_alarm(self):
        try:
            if self.audio_ready and os.path.exists(self.sound_file):
                pygame.mixer.music.load(self.sound_file)
                pygame.mixer.music.play()
        except Exception as e:
            print(f"알람 재생 오류: {e}")

    def show_toast_notification(self, hour):
        try:
            message = f"{hour}시 정각입니다"
            if IS_WINDOWS:
                toast = Notification(app_id="정각 알림", title="⏰ 정각 알림", msg=message, duration="short")
                toast.set_audio(audio.Default, loop=False)
                toast.show()
            elif IS_MACOS:
                self._show_macos_notification(message)
            else:
                print(f"정각 알림: {message}")
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
                "정각 알림을 화면 오른쪽 상단 배너로 표시하려면 macOS 알림 권한이 필요합니다.\n\n지금 알림을 허용하시겠습니까?"
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

    def _show_macos_notification(self, message):
        if self.notification_center is None:
            script = (
                f"display notification {self._apple_script_string(message)} "
                f"with title {self._apple_script_string('정각 알림')}"
            )
            subprocess.run(["osascript", "-e", script], check=False)
            return

        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_("정각 알림")
        content.setBody_(message)

        identifier = f"hourly-alarm-{datetime.datetime.now().timestamp()}"
        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(identifier, content, None)
        self.notification_center.addNotificationRequest_withCompletionHandler_(
            request,
            lambda error: print(f"macOS 알림 표시 오류: {error}") if error else None,
        )

    # ================= 알람 스레드 =================
    def alarm_worker(self):
        last_hour = -1
        while self.running:
            if self.alarm_enabled_value:
                now = datetime.datetime.now()
                if now.minute == 0 and now.second == 0 and now.hour != last_hour:
                    self.play_alarm()
                    self.show_toast_notification(now.hour)
                    last_hour = now.hour
                if now.minute == 1:
                    last_hour = -1
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
        self.tray_icon = pystray.Icon("hourly_alarm", image, "정각 알림", menu)

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
