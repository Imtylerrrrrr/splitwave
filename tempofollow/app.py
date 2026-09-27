# -*- coding: utf-8 -*-
"""템포 추종 재생 (실험용 사이드 앱). 실행: python -m tempofollow"""

import os
import sys
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from common import resource_path, find_ffmpeg
from tempofollow.engine import SR, Engine, default_devices, list_devices
from tempofollow.tempo import estimate_bpm

AUDIO_TYPES = [("오디오 파일", "*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.opus"), ("모든 파일", "*.*")]


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme(resource_path("assets/theme.json"))

        self.title("Tempo Follow")
        self.geometry("480x600")
        self.resizable(False, False)
        self._set_window_icon()

        self.engine = Engine()
        self.running = False
        self.wait_for_hit = True
        inputs, outputs = list_devices()
        self.inputs = {name: idx for idx, name in reversed(inputs)}
        self.outputs = {name: idx for idx, name in reversed(outputs)}

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        if not find_ffmpeg():
            self.set_status("ffmpeg를 찾지 못했습니다. 곡을 불러올 수 없어요. (README 참고)")

    def _set_window_icon(self):
        self._icon_img = ImageTk.PhotoImage(
            Image.open(resource_path("assets/icon.png")).resize((256, 256)))
        self.iconphoto(True, self._icon_img)
        if sys.platform == "win32":
            try:
                self.iconbitmap(resource_path("assets/icon.ico"))
            except Exception:
                pass

    # ── UI 구성 ──
    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(14, 4))
        mark = Image.open(resource_path("assets/mark.png"))
        ctk.CTkLabel(
            header, text="",
            image=ctk.CTkImage(light_image=mark, dark_image=mark, size=(24, 24)),
        ).pack(side="left")
        ctk.CTkLabel(
            header, text="Tempo Follow", font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left", padx=(8, 0))

        small = ctk.CTkFont(size=11)
        gray = {"fg_color": "gray30", "hover_color": "gray25", "text_color": "#F9FAFB"}

        # 1. 곡 파일
        row = self._row("곡 파일")
        ctk.CTkButton(row, text="파일 선택", width=90, command=self.on_choose_file,
                      **gray).pack(side="right")
        self.file_label = ctk.CTkLabel(row, text="선택 안 됨", anchor="w", font=small,
                                       text_color="gray70")
        self.file_label.pack(side="left", padx=(10, 0), fill="x", expand=True)

        # 2. 기본 BPM
        row = self._row("기본 BPM")
        self.bpm_entry = ctk.CTkEntry(row, placeholder_text="예: 120", width=100)
        self.bpm_entry.pack(side="left", padx=(10, 0))
        ctk.CTkButton(row, text="곡에서 추정", width=110, command=self.on_estimate,
                      **gray).pack(side="right")

        # 3. 마이크 / 출력 장치
        in_idx, out_idx = default_devices()
        row = self._row("마이크")
        self.in_menu = ctk.CTkOptionMenu(row, values=list(self.inputs) or ["없음"], width=300)
        self.in_menu.set(self._default_name(self.inputs, in_idx))
        self.in_menu.pack(side="right")
        row = self._row("출력 장치")
        self.out_menu = ctk.CTkOptionMenu(row, values=list(self.outputs) or ["없음"], width=300)
        self.out_menu.set(self._default_name(self.outputs, out_idx))
        self.out_menu.pack(side="right")

        # 4. 추종 범위
        row = self._row("추종 범위 ±")
        self.range_entry = ctk.CTkEntry(row, width=60)
        self.range_entry.insert(0, "30")
        self.range_entry.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(row, text="%").pack(side="left", padx=(4, 0))

        # 5. 첫 타격에 맞춰 시작 + 타격 감도
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(10, 0))
        self.hit_check = ctk.CTkCheckBox(row, text="첫 타격에 맞춰 시작")
        self.hit_check.select()
        self.hit_check.pack(side="left")
        row = self._row("타격 감도")
        self.hit_value = ctk.CTkLabel(row, text="-20 dB", width=60)
        self.hit_value.pack(side="right")
        self.hit_slider = ctk.CTkSlider(
            row, from_=-40, to=-6, number_of_steps=34,
            command=lambda v: self.hit_value.configure(text=f"{int(round(v))} dB"))
        self.hit_slider.set(-20)
        self.hit_slider.pack(side="left", padx=(10, 8), fill="x", expand=True)

        # 6. 마이크 레벨
        row = self._row("마이크 레벨")
        self.level_bar = ctk.CTkProgressBar(row)
        self.level_bar.set(0)
        self.level_bar.pack(side="left", padx=(10, 0), fill="x", expand=True)

        # 7. 큰 숫자 3개 + 진행
        nums = ctk.CTkFrame(self, fg_color="transparent")
        nums.pack(fill="x", padx=20, pady=(16, 0))
        big = ctk.CTkFont(size=28, weight="bold")
        self.num_labels = []
        for col, caption in enumerate(["드럼 BPM", "재생 BPM", "속도"]):
            nums.grid_columnconfigure(col, weight=1)
            value = ctk.CTkLabel(nums, text="-", font=big)
            value.grid(row=0, column=col)
            ctk.CTkLabel(nums, text=caption, font=small, text_color="gray70").grid(
                row=1, column=col)
            self.num_labels.append(value)
        self.progress_label = ctk.CTkLabel(self, text="0:00 / 0:00")
        self.progress_label.pack(pady=(8, 0))

        # 8. 시작/정지 + 상태줄
        self.start_btn = ctk.CTkButton(
            self, text="시작", height=40, font=ctk.CTkFont(size=16, weight="bold"),
            command=self.on_start_stop)
        self.start_btn.pack(fill="x", padx=20, pady=(14, 0))
        self.status_label = ctk.CTkLabel(self, text="대기 중", anchor="w")
        self.status_label.pack(fill="x", padx=20, pady=(6, 0))

    def _row(self, caption: str):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(10, 0))
        ctk.CTkLabel(row, text=caption, anchor="w", width=80).pack(side="left")
        return row

    @staticmethod
    def _default_name(devices: dict, idx) -> str:
        for name, i in devices.items():
            if i == idx:
                return name
        return next(iter(devices), "없음")

    # ── 유틸 ──
    def set_status(self, text: str):
        self.status_label.configure(text=text)

    # ── 곡 불러오기 / BPM 추정 ──
    def on_choose_file(self):
        path = filedialog.askopenfilename(filetypes=AUDIO_TYPES)
        if not path or self.running:
            return
        self.file_label.configure(text=os.path.basename(path))
        self.set_status("불러오는 중…")

        def work():
            try:
                self.engine.load(path)
                msg = f"길이 {fmt_time(self.engine.duration_s)}"
            except Exception as e:
                self.engine.audio = None
                msg = f"불러오기 실패: {e}"
            self.after(0, lambda: self.set_status(msg))

        threading.Thread(target=work, daemon=True).start()

    def on_estimate(self):
        audio = self.engine.audio
        if audio is None:
            self.set_status("먼저 곡 파일을 선택하세요.")
            return
        self.set_status("BPM 추정 중…")

        def work():
            try:
                bpm = estimate_bpm(audio.mean(axis=1), SR)
            except Exception as e:
                self.after(0, lambda: self.set_status(f"BPM 추정 실패: {e}"))
                return

            def done():
                self.bpm_entry.delete(0, "end")
                self.bpm_entry.insert(0, f"{bpm:.1f}")
                self.set_status(f"추정 BPM {bpm:.1f}")
            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    # ── 시작 / 정지 ──
    def on_start_stop(self):
        if self.running:
            self._stop("정지됨")
            return
        if self.engine.audio is None:
            self.set_status("곡 파일을 선택하세요.")
            return
        try:
            bpm = float(self.bpm_entry.get())
            if bpm <= 0:
                raise ValueError
        except ValueError:
            self.set_status("기본 BPM을 0보다 큰 숫자로 입력하세요.")
            return
        try:
            range_pct = float(self.range_entry.get())
            if not 1 <= range_pct <= 90:
                raise ValueError
        except ValueError:
            self.set_status("추종 범위는 1~90 사이 숫자로 입력하세요.")
            return
        if self.in_menu.get() not in self.inputs or self.out_menu.get() not in self.outputs:
            self.set_status("마이크와 출력 장치를 선택하세요.")
            return

        self.wait_for_hit = bool(self.hit_check.get())
        self.engine.start(bpm, self.inputs[self.in_menu.get()],
                          self.outputs[self.out_menu.get()], range_pct,
                          self.wait_for_hit, self.hit_slider.get())
        if self.engine.error:
            self.set_status(f"오류: {self.engine.error}")
            return
        self.running = True
        self.start_btn.configure(text="정지")
        self.set_status("재생 중")
        self.after(100, self._poll)

    def _stop(self, msg: str):
        self.engine.stop()
        self.running = False
        self.start_btn.configure(text="시작")
        self.level_bar.set(0)
        self.set_status(msg)

    def _poll(self):
        if not self.running:
            return
        st = self.engine.status()
        if st["error"]:
            self._stop(f"오류: {st['error']}")
            return
        if st["finished"]:
            self._stop("재생 끝")
            return
        self.level_bar.set(min(max((st["level_db"] + 60) / 60, 0), 1))
        self.num_labels[0].configure(text=f"{st['bpm']:.1f}")
        self.num_labels[1].configure(text=f"{st['playback_bpm']:.1f}")
        self.num_labels[2].configure(text=f"x{st['ratio']:.2f}")
        self.progress_label.configure(
            text=f"{fmt_time(st['position_s'])} / {fmt_time(st['duration_s'])}")
        if self.wait_for_hit and not st["playing"]:
            self.set_status("드럼을 치면 시작합니다")
        elif st["bleed_delay_ms"] is not None:
            self.set_status(f"재생 중 · 스피커 소리 상쇄 중 (지연 {st['bleed_delay_ms']:.0f} ms)")
        else:
            self.set_status("재생 중")
        self.after(100, self._poll)

    def on_close(self):
        self.engine.stop()
        self.destroy()


def main():
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        try:
            messagebox.showerror("오류", f"프로그램 실행 중 오류가 발생했습니다.\n{e}")
        except Exception:
            print(f"오류: {e}", file=sys.stderr)
