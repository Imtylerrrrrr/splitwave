# -*- coding: utf-8 -*-
"""스템 분리 탭.
demucs 가 설치돼 있으면 StemsPage, 없으면(라이트 버전) LitePlaceholder 를 만든다.
demucs/torch 는 여기서 최상단 import 하지 않는다 — 라이트 환경에서도 이 모듈은 로드돼야 한다."""

import os
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import yt_dlp

from common import (
    KEY_VALUES, KEY_HELP, parse_key, is_youtube_url,
    translate_error, collect_filepaths, open_path,
)


def stems_available() -> bool:
    """풀 버전 여부는 오직 demucs import 가능 여부로 판단한다."""
    try:
        import demucs.api
    except ImportError:
        return False
    return demucs.api is not None


LITE_NOTICE = (
    "스템 분리는 풀 버전에서 지원돼요.\n\n"
    "• 풀 버전(zip)을 받아서 실행하거나\n"
    "• 소스로 실행 중이라면 터미널에서\n"
    "    pip install -r requirements-stems.txt\n"
    "  를 실행한 뒤 프로그램을 다시 켜 주세요.\n\n"
    "(풀 버전은 PyTorch가 들어 있어 수백 MB예요)"
)


class LitePlaceholder(ctk.CTkFrame):
    """라이트 버전에서 스템 탭에 보여줄 안내."""

    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="both", expand=True)
        ctk.CTkLabel(
            self, text=LITE_NOTICE, justify="left", anchor="w",
            font=ctk.CTkFont(size=13),
        ).pack(fill="x", padx=20, pady=30)


FORMAT_LABELS = ["WAV", "MP3 320kbps"]
FORMAT_TO_EXT = {"WAV": "wav", "MP3 320kbps": "mp3"}

AUDIO_FILETYPES = [("오디오 파일", "*.mp3 *.m4a *.wav *.opus *.webm *.ogg *.flac"),
                   ("모든 파일", "*.*")]


class StemsPage(ctk.CTkFrame):
    """스템 분리 탭. 입력(파일 or 링크) → separator.separate → 폴더에 저장."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="both", expand=True)
        self.app = app
        self.file_path: str | None = None
        self.out_dir: str | None = None
        self._build()
        app.folder_listeners.append(lambda d: self.folder_label.configure(text=d))

    # ── UI ──
    def _build(self):
        from separator import STEM_LABELS, STEM_ORDER, DEFAULT_STEMS
        pad = {"padx": 20, "pady": (10, 0)}

        ctk.CTkLabel(self, text="유튜브 링크 또는 음원 파일 (파일이 우선):", anchor="w").pack(fill="x", **pad)
        self.url_entry = ctk.CTkEntry(self, placeholder_text="https://www.youtube.com/watch?v=...")
        self.url_entry.pack(fill="x", padx=20, pady=(4, 0))

        file_row = ctk.CTkFrame(self, fg_color="transparent")
        file_row.pack(fill="x", padx=20, pady=(6, 0))
        ctk.CTkButton(file_row, text="파일 선택", width=110,
                      fg_color="gray30", hover_color="gray25", text_color="#F9FAFB",
                      command=self.on_choose_file).pack(side="left")
        ctk.CTkButton(file_row, text="지우기", width=64,
                      fg_color="gray30", hover_color="gray25", text_color="#F9FAFB",
                      command=self.on_clear_file).pack(side="left", padx=(6, 0))
        self.file_label = ctk.CTkLabel(file_row, text="(선택 안 함)", anchor="w",
                                       font=ctk.CTkFont(size=11), text_color="gray70")
        self.file_label.pack(side="left", padx=(10, 0), fill="x", expand=True)

        ctk.CTkLabel(self, text="저장할 스템:", anchor="w").pack(fill="x", **pad)
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=20, pady=(4, 0))
        self.stem_vars: dict[str, ctk.BooleanVar] = {}
        for i, name in enumerate(STEM_ORDER):
            var = ctk.BooleanVar(value=name in DEFAULT_STEMS)
            self.stem_vars[name] = var
            ctk.CTkCheckBox(grid, text=STEM_LABELS[name], variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 16), pady=2)
        ctk.CTkLabel(
            self, text="기타·건반 분리는 보컬·드럼보다 품질이 낮을 수 있어요.",
            justify="left", anchor="w", font=ctk.CTkFont(size=11), text_color="gray70",
        ).pack(fill="x", padx=20, pady=(4, 0))

        opt_row = ctk.CTkFrame(self, fg_color="transparent")
        opt_row.pack(fill="x", padx=20, pady=(10, 0))
        ctk.CTkLabel(opt_row, text="출력 포맷:").pack(side="left")
        self.format_menu = ctk.CTkOptionMenu(opt_row, values=FORMAT_LABELS, width=130)
        self.format_menu.set(FORMAT_LABELS[0])
        self.format_menu.pack(side="left", padx=(8, 20))
        ctk.CTkLabel(opt_row, text="키 조정 (반음):").pack(side="left")
        self.key_menu = ctk.CTkOptionMenu(opt_row, values=KEY_VALUES, width=110)
        self.key_menu.set("0 (원본)")
        self.key_menu.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(self, text=KEY_HELP, justify="left", anchor="w",
                     font=ctk.CTkFont(size=11), text_color="gray70").pack(fill="x", padx=20, pady=(4, 0))

        folder_row = ctk.CTkFrame(self, fg_color="transparent")
        folder_row.pack(fill="x", padx=20, pady=(10, 0))
        ctk.CTkButton(folder_row, text="저장 폴더 선택", width=130,
                      fg_color="gray30", hover_color="gray25", text_color="#F9FAFB",
                      command=self.app.choose_folder).pack(side="left")
        self.folder_label = ctk.CTkLabel(folder_row, text=self.app.save_dir, anchor="w",
                                         font=ctk.CTkFont(size=11), text_color="gray70")
        self.folder_label.pack(side="left", padx=(10, 0), fill="x", expand=True)

        self.start_btn = ctk.CTkButton(self, text="분리 시작", height=40,
                                       font=ctk.CTkFont(size=16, weight="bold"),
                                       command=self.on_start_click)
        self.start_btn.pack(fill="x", padx=20, pady=(14, 0))

        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=20, pady=(14, 0))
        self.status_label = ctk.CTkLabel(self, text="대기 중", anchor="w")
        self.status_label.pack(fill="x", padx=20, pady=(6, 0))

        self.open_btn = ctk.CTkButton(self, text="결과 폴더 열기", command=self.open_result,
                                      fg_color="gray30", hover_color="gray25", text_color="#F9FAFB",
                                      state="disabled")
        self.open_btn.pack(fill="x", padx=20, pady=(10, 16))

    # ── 유틸 ──
    def set_status(self, text: str):
        self.status_label.configure(text=text)

    def selected_stems(self) -> list[str]:
        from separator import STEM_ORDER
        return [n for n in STEM_ORDER if self.stem_vars[n].get()]

    def resolve_input(self):
        """("file", 경로) / ("url", 링크) / None. 파일이 링크보다 우선."""
        if self.file_path:
            return ("file", self.file_path)
        url = self.url_entry.get().strip()
        if url:
            return ("url", url)
        return None

    def on_choose_file(self):
        chosen = filedialog.askopenfilename(title="분리할 음원 파일 선택", filetypes=AUDIO_FILETYPES)
        if chosen:
            self.file_path = chosen
            self.file_label.configure(text=os.path.basename(chosen))

    def on_clear_file(self):
        self.file_path = None
        self.file_label.configure(text="(선택 안 함)")

    def open_result(self):
        open_path(self.out_dir or self.app.save_dir)

    # ── 시작 ──
    def on_start_click(self):
        if self.app.busy:
            messagebox.showinfo("안내", "다른 작업이 진행 중이에요. 끝난 뒤 다시 시도해 주세요.")
            return
        src = self.resolve_input()
        if src is None:
            messagebox.showwarning("안내", "유튜브 링크를 붙여넣거나 음원 파일을 선택해 주세요!")
            return
        if src[0] == "url" and not is_youtube_url(src[1]):
            messagebox.showwarning("안내", "유튜브 링크가 아닌 것 같아요.\n"
                                   "youtube.com 또는 youtu.be 로 시작하는 주소를 넣어 주세요.")
            return
        stems = self.selected_stems()
        if not stems:
            messagebox.showwarning("안내", "저장할 스템을 하나 이상 체크해 주세요.")
            return
        if not self.app.ffmpeg_path:
            messagebox.showerror("FFmpeg 없음",
                                 "스템 분리에는 FFmpeg가 필요한데 찾지 못했습니다.\n"
                                 "ffmpeg.exe 를 이 프로그램과 같은 폴더에 넣어 주세요. (README 참고)")
            return

        fmt = FORMAT_TO_EXT[self.format_menu.get()]
        semitones = parse_key(self.key_menu.get())

        self.app.busy = True
        self.start_btn.configure(state="disabled", text="분리 중...")
        self.open_btn.configure(state="disabled")
        self.progress.set(0)
        self.set_status("준비 중...")
        threading.Thread(
            target=self._worker, args=(src, stems, fmt, semitones), daemon=True,
        ).start()

    # ── 워커 (별도 스레드) ──
    def _worker(self, src, stems, fmt, semitones):
        stage = "download"
        try:
            kind, value = src
            input_path = self._download(value) if kind == "url" else value
            stage = "separate"
            from separator import separate, translate_stem_error  # 지연 import (torch 로딩)
            out_dir = os.path.join(self.app.save_dir, f"{Path(input_path).stem}_stems")
            saved = separate(
                input_path, stems, out_dir, fmt, self.app.ffmpeg_path, semitones,
                on_progress=lambda frac, text: self.app.after(
                    0, lambda: (self.progress.set(frac), self.set_status(text))),
            )
            self.app.after(0, lambda: self._on_done(out_dir, saved))
        except Exception as e:
            if stage == "separate":
                from separator import translate_stem_error
                msg = translate_stem_error(e)
            else:
                msg = translate_error(e)
            self.app.after(0, lambda: self._on_error(msg))

    def _download(self, url: str) -> str:
        """링크를 m4a 로 받아 경로를 돌려준다 (다운로드 탭과 같은 옵션, 재생목록은 첫 곡만)."""
        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": os.path.join(self.app.save_dir, "%(title)s.%(ext)s"),
            "windowsfilenames": True,
            "noplaylist": True,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "retries": 3,
        }
        if self.app.ffmpeg_path:
            ydl_opts["ffmpeg_location"] = self.app.ffmpeg_path
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        paths = collect_filepaths(info)
        if not paths:
            raise RuntimeError("다운로드한 파일을 찾지 못했습니다.")
        return paths[0]

    def _progress_hook(self, d: dict):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0
            text = f"다운로드 중... {frac * 100:.1f}%"
            self.app.after(0, lambda: (self.progress.set(frac * 0.3), self.set_status(text)))

    # ── 완료 / 실패 (메인 스레드) ──
    def _on_done(self, out_dir: str, saved: list[str]):
        self.app.busy = False
        self.out_dir = out_dir
        self.start_btn.configure(state="normal", text="분리 시작")
        self.open_btn.configure(state="normal")
        self.progress.set(1.0)
        self.set_status(f"완료: {len(saved)}개 스템 저장")
        names = "\n".join(os.path.basename(p) for p in saved)
        messagebox.showinfo("완료", f"스템 분리가 끝났습니다.\n\n{names}\n\n폴더:\n{out_dir}")

    def _on_error(self, korean_msg: str):
        self.app.busy = False
        self.start_btn.configure(state="normal", text="분리 시작")
        self.progress.set(0)
        self.set_status("실패 — 아래 안내를 확인하세요.")
        messagebox.showerror("스템 분리 실패", korean_msg)


def make_stems_tab(parent, app) -> ctk.CTkFrame:
    if not stems_available():
        return LitePlaceholder(parent)
    return StemsPage(parent, app)
