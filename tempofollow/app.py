# -*- coding: utf-8 -*-
"""템포 추종 재생 (실험용 사이드 앱). 실행: python -m tempofollow"""

import os
import sys
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

from common import resource_path, find_ffmpeg
from library import base_dir, library_dir, list_tracks, load_settings, menu_labels, save_settings
from tempofollow.engine import SR, Engine, default_devices, list_devices
from tempofollow.tempo import estimate_bpm

AUDIO_TYPES = [("오디오 파일", "*.mp3 *.wav *.m4a *.flac *.ogg *.aac *.opus"), ("모든 파일", "*.*")]

LIBRARY_GUIDE_ITEM = "(보관함에서 고르기)"
LIBRARY_EMPTY_ITEM = "(받은 곡이 없어요)"
SETTINGS_KEY = "tempofollow"    # 공용 설정 파일 안에서 이 앱이 쓰는 항목


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def library_menu(lib: str) -> dict[str, str]:
    """보관함 드롭다운 항목. 안내 항목과 빈 목록 문구는 포함하지 않는다."""
    return menu_labels(list_tracks(lib))


def song_file_for(tracks, path: str) -> str | None:
    """스템 path 와 같은 묶음의 곡 파일 경로. 곡 자체를 골랐거나 곡 파일이 없으면 None.
    곡 파일은 드럼이 있어 박을 찾기 좋고, 스템과 길이가 같다."""
    for t in tracks:
        if t.path == path and t.stem is not None:
            return next((s.path for s in tracks if s.song == t.song and s.stem is None), None)
    return None


def status_text(st: dict, wait_for_hit: bool) -> str:
    """재생 중 상태줄 문구. st 는 Engine.status()."""
    if wait_for_hit and not st["playing"]:
        return "드럼을 치면 시작합니다"
    parts = ["따라가는 중" if st.get("locked") else "템포 찾는 중"]
    if st.get("beats_ok") is False:
        parts.append("곡에서 박을 못 찾아 박자 맞춤은 꺼짐")
    elif st.get("locked") and st.get("phase_ms") is not None:
        parts.append(f"박자 오차 {st['phase_ms']:+.0f} ms")
    if st.get("bleed_delay_ms") is not None:
        parts.append(f"스피커 소리 상쇄 중 (지연 {st['bleed_delay_ms']:.0f} ms)")
    return " · ".join(parts)


def menu_values(items: dict[str, str]) -> list[str]:
    """드롭다운에 표시할 목록. 항목이 있으면 안내 항목을 맨 앞에 붙이고,
    없으면 빈 목록 문구 하나만 돌려준다."""
    if items:
        return [LIBRARY_GUIDE_ITEM] + list(items)
    return [LIBRARY_EMPTY_ITEM]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme(resource_path("assets/theme.json"))

        self.title("Tempo Follow")
        self.geometry("560x690")
        self.resizable(False, False)
        self._set_window_icon()

        self.engine = Engine()
        self.running = False
        self.wait_for_hit = True
        inputs, outputs = list_devices()
        self.inputs = {name: idx for idx, name in reversed(inputs)}
        self.outputs = {name: idx for idx, name in reversed(outputs)}

        self._build_ui()
        self._apply_settings()
        self.on_refresh_library()
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

        # 보관함
        row = self._row("보관함")
        ctk.CTkButton(row, text="새로고침", width=90, command=self.on_refresh_library,
                      **gray).pack(side="right")
        self.library_menu = ctk.CTkOptionMenu(
            row, values=[LIBRARY_EMPTY_ITEM], width=340, dynamic_resizing=False,
            command=self.on_choose_library)
        self.library_menu.pack(side="left", padx=(10, 0))

        # 2. 기본 BPM
        row = self._row("기본 BPM")
        self.bpm_entry = ctk.CTkEntry(row, placeholder_text="예: 120", width=100)
        self.bpm_entry.pack(side="left", padx=(10, 0))
        ctk.CTkButton(row, text="곡에서 추정", width=110, command=self.on_estimate,
                      **gray).pack(side="right")

        # 3. 마이크 / 출력 장치
        in_idx, out_idx = default_devices()
        row = self._row("마이크")
        self.in_menu = ctk.CTkOptionMenu(row, values=list(self.inputs) or ["없음"], width=380)
        self.in_menu.set(self._default_name(self.inputs, in_idx))
        self.in_menu.pack(side="right")
        row = self._row("출력 장치")
        self.out_menu = ctk.CTkOptionMenu(row, values=list(self.outputs) or ["없음"], width=380)
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
        self.phase_check = ctk.CTkCheckBox(row, text="박자 위치도 맞춤")
        self.phase_check.select()
        self.phase_check.pack(side="left", padx=(20, 0))
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
        for col, caption in enumerate(["드럼 BPM", "재생 BPM", "속도", "박자 오차"]):
            nums.grid_columnconfigure(col, weight=1)
            value = ctk.CTkLabel(nums, text="-", font=big)
            value.grid(row=0, column=col)
            ctk.CTkLabel(nums, text=caption, font=small, text_color="gray70").grid(
                row=1, column=col)
            self.num_labels.append(value)
        self.pos_bar = ctk.CTkProgressBar(self)
        self.pos_bar.set(0)
        self.pos_bar.pack(fill="x", padx=20, pady=(12, 0))
        self.progress_label = ctk.CTkLabel(self, text="0:00 / 0:00")
        self.progress_label.pack(pady=(4, 0))

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

    def _apply_settings(self):
        """지난번 장치·감도·체크 상태를 공용 설정 파일에서 되살린다. 없는 장치는 건너뛴다."""
        s = load_settings().get(SETTINGS_KEY, {})
        if not isinstance(s, dict):
            return
        if s.get("input") in self.inputs:
            self.in_menu.set(s["input"])
        if s.get("output") in self.outputs:
            self.out_menu.set(s["output"])
        if isinstance(s.get("hit_db"), (int, float)):
            self.hit_slider.set(s["hit_db"])
            self.hit_value.configure(text=f"{int(round(s['hit_db']))} dB")
        if isinstance(s.get("range_pct"), (int, float)):
            self.range_entry.delete(0, "end")
            self.range_entry.insert(0, f"{s['range_pct']:g}")
        for key, box in (("wait_for_hit", self.hit_check), ("follow_phase", self.phase_check)):
            if key in s:
                box.select() if s[key] else box.deselect()

    def _save_settings(self):
        settings = load_settings()
        try:
            range_pct = float(self.range_entry.get())
        except ValueError:
            range_pct = None
        settings[SETTINGS_KEY] = dict(
            input=self.in_menu.get(), output=self.out_menu.get(),
            hit_db=float(self.hit_slider.get()), range_pct=range_pct,
            wait_for_hit=bool(self.hit_check.get()), follow_phase=bool(self.phase_check.get()))
        save_settings(settings)

    # ── 곡 불러오기 / BPM 추정 ──
    def on_choose_file(self):
        path = filedialog.askopenfilename(filetypes=AUDIO_TYPES)
        if not path or self.running:
            return
        self._load_file(path)

    def _load_file(self, path, beat_path=None):
        """곡을 불러오고 BPM 을 추정해 채운다. beat_path 는 박을 찾을 원곡(없으면 곡 자체)."""
        self.file_label.configure(text=os.path.basename(path))
        self.set_status("불러오는 중…")

        def work():
            try:
                self.engine.load(path, beat_path)
            except Exception as e:
                self.engine.audio = None
                self.after(0, lambda: self.set_status(f"불러오기 실패: {e}"))
                return
            length = fmt_time(self.engine.duration_s)
            try:
                bpm = estimate_bpm(self.engine.beat_source, SR)
            except Exception:
                self.after(0, lambda: self.set_status(
                    f"길이 {length} · BPM 을 추정하지 못했어요. 직접 입력하세요."))
                return

            def done():
                self.bpm_entry.delete(0, "end")
                self.bpm_entry.insert(0, f"{bpm:.1f}")
                self.set_status(f"길이 {length} · 추정 BPM {bpm:.1f} (틀리면 고치세요)")
            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def on_refresh_library(self):
        lib = library_dir(base_dir())
        self.library_tracks = list_tracks(lib)
        self.library_items = menu_labels(self.library_tracks)
        values = menu_values(self.library_items)
        self.library_menu.configure(values=values)
        self.library_menu.set(values[0])

    def on_choose_library(self, value):
        if self.running:
            self.library_menu.set(menu_values(self.library_items)[0])
            return
        path = self.library_items.get(value)
        if path is None:
            return
        self._load_file(path, song_file_for(self.library_tracks, path))

    def on_estimate(self):
        source = self.engine.beat_source
        if source is None:
            self.set_status("먼저 곡 파일을 선택하세요.")
            return
        self.set_status("BPM 추정 중…")

        def work():
            try:
                bpm = estimate_bpm(source, SR)
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
        self._save_settings()
        self.engine.start(bpm, self.inputs[self.in_menu.get()],
                          self.outputs[self.out_menu.get()], range_pct,
                          self.wait_for_hit, self.hit_slider.get(),
                          follow_phase=bool(self.phase_check.get()))
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
        self.num_labels[3].configure(
            text="-" if st["phase_ms"] is None else f"{st['phase_ms']:+.0f} ms")
        self.pos_bar.set(min(st["position_s"] / st["duration_s"], 1.0) if st["duration_s"] else 0)
        self.progress_label.configure(
            text=f"{fmt_time(st['position_s'])} / {fmt_time(st['duration_s'])}")
        self.set_status(status_text(st, self.wait_for_hit))
        self.after(100, self._poll)

    def on_close(self):
        self.engine.stop()
        self._save_settings()
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
