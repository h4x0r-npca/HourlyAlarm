import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import time
import datetime
import os
import sys
import ctypes

import pygame
import pystray
from PIL import Image, ImageDraw, ImageTk
import win32com.client
from winotify import Notification, audio

def resource_path(rel_path: str) -> str:
    import sys, os
    if hasattr(sys, "_MEIPASS"):  # PyInstaller onefile 임시폴더
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)


class HourlyAlarmApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("정각 알림 프로그램")
        self.root.geometry("380x450")
        self.root.resizable(False, False)

        # ===== 상태 변수 =====
        self.alarm_enabled = tk.BooleanVar(value=True)
        self.autostart_enabled = tk.BooleanVar(value=False)

        # ★ 기본 알림음 경로 + 현재 사용 음원 경로
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.default_sound_file = resource_path("Ring10.wav")
        self.sound_file = self.default_sound_file

        self.running = True
        self.alarm_thread = None
        self.tray_icon = None
        self._tray_thread_started = False

        # pygame 초기화
        pygame.mixer.init()

        # 자동 시작 상태 확인
        self.check_autostart_status()

        # 트레이 아이콘은 항상 띄워둠
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

        # 시작 시 트레이로 최소화
        self.root.after(100, self.start_minimized_to_tray)

    # ================= GUI =================
    def setup_gui(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        title_label = ttk.Label(main_frame, text="⏰ 정각 알림 프로그램", font=("맑은 고딕", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))

        alarm_check = ttk.Checkbutton(
            main_frame, text="정각 알림 활성화",
            variable=self.alarm_enabled, command=self.toggle_alarm
        )
        alarm_check.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=10)

        autostart_check = ttk.Checkbutton(
            main_frame, text="컴퓨터 시작 시 자동 실행",
            variable=self.autostart_enabled, command=self.toggle_autostart
        )
        autostart_check.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=10)

        separator1 = ttk.Separator(main_frame, orient='horizontal')
        separator1.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=15)

        sound_label = ttk.Label(main_frame, text="알림 사운드:", font=("맑은 고딕", 10, "bold"))
        sound_label.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(0, 5))

        # 사운드 파일 표시(초기엔 '기본알림음'으로 표시)
        self.sound_file_label = ttk.Label(
            main_frame, text="", foreground="blue", wraplength=330, anchor="w", justify="left"
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

        button_frame.grid_columnconfigure(0, weight=1)
        button_frame.grid_columnconfigure(1, weight=1)
        button_frame.grid_columnconfigure(2, weight=1)

        separator2 = ttk.Separator(main_frame, orient='horizontal')
        separator2.grid(row=7, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=15)

        # ── 현재 시간 라인을 한 줄에 배치 (pack 사용)
        time_row = ttk.Frame(main_frame)
        time_row.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 0))

        lbl_now = ttk.Label(time_row, text="현재 시간:", font=("맑은 고딕", 10))
        lbl_now.pack(side="left", padx=(0, 8))

        self.current_time_label = ttk.Label(
            time_row,
            text="",
            font=("맑은 고딕", 12, "bold"),
            foreground="green",
            anchor="w",     # 라벨 내부 좌측 정렬
            justify="left"
        )
        self.current_time_label.pack(side="left")
        # 제작자 표기
        self.author_label = ttk.Label(
            main_frame,
            text="제작자  Kyo : dersertfox@kakao.com",
            font=("맑은 고딕", 9),
            foreground="#6b7280"
        )
        self.author_label.grid(row=9, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))

        ttk.Button(main_frame, text="시스템 트레이로 최소화", command=self.minimize_to_tray)\
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
        if self.alarm_enabled.get():
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
            startup_folder = os.path.join(os.getenv('APPDATA'), r'Microsoft\Windows\Start Menu\Programs\Startup')
            self.autostart_enabled.set(os.path.exists(os.path.join(startup_folder, "HourlyAlarm.lnk")))
        except Exception as e:
            print(f"자동 시작 상태 확인 오류: {e}")

    def add_to_startup(self):
        try:
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
            startup_folder = os.path.join(os.getenv('APPDATA'), r'Microsoft\Windows\Start Menu\Programs\Startup')
            shortcut_path = os.path.join(startup_folder, "HourlyAlarm.lnk")
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
            return True
        except Exception as e:
            print(f"시작 프로그램 제거 오류: {e}")
            return False

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
        try:
            pygame.mixer.music.load(self.sound_file)
            pygame.mixer.music.play()
        except Exception as e:
            messagebox.showerror("오류", f"사운드 재생 실패: {e}")

    def play_alarm(self):
        try:
            if os.path.exists(self.sound_file):
                pygame.mixer.music.load(self.sound_file)
                pygame.mixer.music.play()
        except Exception as e:
            print(f"알람 재생 오류: {e}")

    def show_toast_notification(self, hour):
        try:
            toast = Notification(app_id="정각 알림", title="⏰ 정각 알림", msg=f"{hour}시 정각입니다", duration="short")
            toast.set_audio(audio.Default, loop=False)
            toast.show()
        except Exception as e:
            print(f"토스트 알림 오류: {e}")

    # ================= 알람 스레드 =================
    def alarm_worker(self):
        last_hour = -1
        while self.running:
            if self.alarm_enabled.get():
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
        """시스템 트레이 아이콘 생성 — 항상 유지"""
        image = self._make_clock_icon(64)
        menu = pystray.Menu(
            pystray.MenuItem("열기", self.show_window, default=True),  # 더블클릭 = 열기
            pystray.MenuItem("종료", self.quit_app)
        )
        self.tray_icon = pystray.Icon("hourly_alarm", image, "정각 알림", menu)

    def _ensure_tray_running(self):
        """아이콘 런루프를 한 번만 실행"""
        if self.tray_icon and not self._tray_thread_started:
            t = threading.Thread(target=self.tray_icon.run, daemon=True)
            t.start()
            self._tray_thread_started = True

    def minimize_to_tray(self):
        """트레이로 최소화(종료 아님). 아이콘은 항상 유지."""
        self.root.withdraw()
        self._ensure_tray_running()

    def start_minimized_to_tray(self):
        self.minimize_to_tray()

    def show_window(self, icon=None, item=None):
        """창 보이기 — 최상위로 노출"""
        self._ensure_tray_running()
        try:
            self.root.deiconify()
            self.root.state('normal')
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.after(150, lambda: self.root.attributes('-topmost', False))
            self.root.after(200, self.root.focus_force)
        except Exception:
            pass

    def quit_app(self, icon=None, item=None):
        """종료(오직 트레이 메뉴에서만 호출)"""
        self.running = False
        try:
            if self.tray_icon:
                self.tray_icon.stop()
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
