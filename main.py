# -*- coding: utf-8 -*-
"""
유튜브 오디오(MR/반주) 다운로더
- yt-dlp + FFmpeg + customtkinter
- Windows 단일 .exe 패키징(PyInstaller) 대응
"""

import os
import sys
import json
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk
import yt_dlp
from common import (
    resource_path, find_ffmpeg, KEY_VALUES, KEY_HELP, parse_key, shift_pitch,
    is_youtube_url, is_playlist_url, translate_error,
    collect_filepaths, open_path,
)


# ──────────────────────────────────────────────
# 설정 저장 (마지막 사용 폴더 기억)
# ──────────────────────────────────────────────

def config_path() -> Path:
    """설정 파일 위치: Windows는 %APPDATA%, 그 외엔 홈 폴더."""
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "yt_audio_downloader_config.json"


def load_settings() -> dict:
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 설정 저장 실패는 치명적이지 않으므로 무시


def default_download_dir() -> str:
    """기본 저장 폴더 = 사용자 다운로드 폴더."""
    d = Path.home() / "Downloads"
    return str(d if d.is_dir() else Path.home())


# ──────────────────────────────────────────────
# 포맷 프리셋
# ──────────────────────────────────────────────

FORMAT_LABELS = [
    "원본 최고음질 (재인코딩 없음)",
    "원본 최고음질 (m4a)",
    "MP3 320kbps",
    "WAV",
]

FORMAT_HELP = "원본/m4a는 FFmpeg 없이도 됩니다. MP3·WAV로 바꿔도 음질이 좋아지진 않아요."


def build_format_opts(label: str) -> dict:
    """선택한 포맷 라벨 → yt-dlp 옵션 조각."""
    if label == "원본 최고음질 (재인코딩 없음)":
        return {"format": "bestaudio/best", "postprocessors": []}
    if label == "원본 최고음질 (m4a)":
        return {"format": "bestaudio[ext=m4a]/bestaudio", "postprocessors": []}
    if label == "MP3 320kbps":
        return {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }],
        }
    if label == "WAV":
        return {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
            }],
        }
    # 알 수 없는 라벨이면 안전하게 기본값
    return {"format": "bestaudio/best", "postprocessors": []}




# ──────────────────────────────────────────────
# GUI 앱
# ──────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")  # 다크모드 기본
        ctk.set_default_color_theme(resource_path("assets/theme.json"))

        self.title("Splitwave")
        self.geometry("560x740")
        self.resizable(False, False)
        self._set_window_icon()

        # 상태
        self.settings = load_settings()
        self.save_dir = self.settings.get("last_dir") or default_download_dir()
        if not os.path.isdir(self.save_dir):
            self.save_dir = default_download_dir()
        self.ffmpeg_path = find_ffmpeg()
        self.busy = False   # 다운로드/스템 분리 중 하나라도 돌고 있으면 True
        self.folder_listeners = []   # 저장 폴더가 바뀌면 호출할 콜백들 (스템 탭이 등록)

        self._build_ui()

        # FFmpeg 미발견 시 미리 경고 (변환 포맷 선택 시 필요)
        if not self.ffmpeg_path:
            self.set_status(
                "ffmpeg.exe를 찾지 못했습니다. MP3/WAV 변환은 불가능합니다. (README 참고)"
            )

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
            header, text="splitwave", font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left", padx=(8, 0))

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        dl_tab = self.tabview.add("다운로드")
        stems_tab = self.tabview.add("스템 분리")
        self._build_download_tab(dl_tab)

        from stems_page import make_stems_tab   # 지연 import (라이트/풀 공통)
        self.stems_page = make_stems_tab(stems_tab, self)

    def _build_download_tab(self, root):
        pad = {"padx": 20, "pady": (10, 0)}

        # URL 입력
        ctk.CTkLabel(root, text="유튜브 링크를 붙여넣으세요:", anchor="w").pack(
            fill="x", **pad)
        self.url_entry = ctk.CTkEntry(
            root, placeholder_text="https://www.youtube.com/watch?v=...")
        self.url_entry.pack(fill="x", padx=20, pady=(4, 0))

        # 포맷 드롭다운 + 안내문
        ctk.CTkLabel(root, text="출력 포맷 / 품질:", anchor="w").pack(fill="x", **pad)
        self.format_menu = ctk.CTkOptionMenu(root, values=FORMAT_LABELS)
        self.format_menu.set(FORMAT_LABELS[1])  # 기본값: m4a (아이폰 등 호환성 좋음)
        self.format_menu.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkLabel(
            root, text=FORMAT_HELP, justify="left", anchor="w",
            font=ctk.CTkFont(size=11), text_color="gray70",
        ).pack(fill="x", padx=20, pady=(4, 0))

        # 키 조정 드롭다운 + 기존 파일 키 조정 버튼
        key_row = ctk.CTkFrame(root, fg_color="transparent")
        key_row.pack(fill="x", padx=20, pady=(10, 0))
        ctk.CTkLabel(key_row, text="키 조정 (반음):").pack(side="left")
        self.key_menu = ctk.CTkOptionMenu(key_row, values=KEY_VALUES, width=110)
        self.key_menu.set("0 (원본)")  # 기본값: 키 변경 없음
        self.key_menu.pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            key_row, text="기존 파일 키 조정", width=160,
            fg_color="gray30", hover_color="gray25", text_color="#F9FAFB",
            command=self.on_shift_existing_click,
        ).pack(side="right")
        ctk.CTkLabel(
            root, text=KEY_HELP, justify="left", anchor="w",
            font=ctk.CTkFont(size=11), text_color="gray70",
        ).pack(fill="x", padx=20, pady=(4, 0))

        # 저장 폴더
        folder_row = ctk.CTkFrame(root, fg_color="transparent")
        folder_row.pack(fill="x", padx=20, pady=(10, 0))
        ctk.CTkButton(
            folder_row, text="저장 폴더 선택", width=130,
            fg_color="gray30", hover_color="gray25", text_color="#F9FAFB",
            command=self.choose_folder,
        ).pack(side="left")
        self.folder_label = ctk.CTkLabel(
            folder_row, text=self.save_dir, anchor="w",
            font=ctk.CTkFont(size=11), text_color="gray70",
        )
        self.folder_label.pack(side="left", padx=(10, 0), fill="x", expand=True)

        # 다운로드 버튼
        self.download_btn = ctk.CTkButton(
            root, text="다운로드", height=40,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.on_download_click,
        )
        self.download_btn.pack(fill="x", padx=20, pady=(14, 0))

        # 진행률
        self.progress = ctk.CTkProgressBar(root)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=20, pady=(14, 0))
        self.status_label = ctk.CTkLabel(root, text="대기 중", anchor="w")
        self.status_label.pack(fill="x", padx=20, pady=(6, 0))

        # 폴더 열기
        self.open_btn = ctk.CTkButton(
            root, text="폴더 열기", command=self.open_folder,
            fg_color="gray30", hover_color="gray25", text_color="#F9FAFB",
        )
        self.open_btn.pack(fill="x", padx=20, pady=(10, 16))

    # ── 유틸 ──
    def set_status(self, text: str):
        self.status_label.configure(text=text)

    def choose_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.save_dir)
        if chosen:
            self.save_dir = chosen
            self.folder_label.configure(text=chosen)
            # 마지막 사용 폴더 기억
            self.settings["last_dir"] = chosen
            save_settings(self.settings)
            for cb in self.folder_listeners:
                cb(chosen)

    def open_folder(self):
        open_path(self.save_dir)

    # ── 다운로드 시작 ──
    def on_download_click(self):
        if self.busy:
            messagebox.showinfo("안내", "다른 작업이 진행 중이에요. 끝난 뒤 다시 시도해 주세요.")
            return

        url = self.url_entry.get().strip()

        # 입력 검증 (한국어 안내)
        if not url:
            messagebox.showwarning("안내", "유튜브 링크를 먼저 붙여넣어 주세요!")
            return
        if not is_youtube_url(url):
            messagebox.showwarning(
                "안내",
                "유튜브 링크가 아닌 것 같아요.\n"
                "youtube.com 또는 youtu.be 로 시작하는 주소를 넣어 주세요.")
            return

        fmt_label = self.format_menu.get()
        semitones = parse_key(self.key_menu.get())

        # 변환 포맷이거나 키 조정이 필요한데 ffmpeg가 없으면 미리 차단
        needs_ffmpeg = fmt_label in ("MP3 320kbps", "WAV") or semitones != 0
        if needs_ffmpeg and not self.ffmpeg_path:
            messagebox.showerror(
                "FFmpeg 없음",
                "MP3/WAV 변환과 키 조정에는 FFmpeg가 필요한데 찾지 못했습니다.\n\n"
                "해결 방법:\n"
                "1) ffmpeg.exe 를 이 프로그램과 같은 폴더에 넣기 (가장 쉬움)\n"
                "2) 또는 https://www.gyan.dev/ffmpeg/builds/ 에서 받아 PATH에 추가\n\n"
                "자세한 방법은 README를 참고하세요.")
            return

        # 재생목록 URL이면 선택지 제공
        noplaylist = True
        if is_playlist_url(url):
            whole = messagebox.askyesno(
                "재생목록 감지",
                "재생목록 링크입니다.\n\n"
                "예(Y): 재생목록 전체 받기\n"
                "아니오(N): 첫 영상만 받기")
            noplaylist = not whole

        # 별도 스레드에서 실행 → GUI 멈춤 방지
        self.busy = True
        self.download_btn.configure(state="disabled", text="다운로드 중...")
        self.progress.set(0)
        self.set_status("영상 정보를 가져오는 중...")

        threading.Thread(
            target=self._download_worker,
            args=(url, fmt_label, noplaylist, semitones),
            daemon=True,
        ).start()

    # ── 다운로드 워커 (별도 스레드) ──
    def _download_worker(self, url: str, fmt_label: str, noplaylist: bool,
                         semitones: int):
        try:
            opts = build_format_opts(fmt_label)
            ydl_opts = {
                # 파일명: 영상 제목 기반.
                # windowsfilenames=True 가 Windows 금지문자(\ / : * ? " < > |)를
                # 자동으로 안전한 문자로 치환/제거해 준다.
                "outtmpl": os.path.join(self.save_dir, "%(title)s.%(ext)s"),
                "windowsfilenames": True,
                "noplaylist": noplaylist,
                "progress_hooks": [self._progress_hook],
                "quiet": True,
                "no_warnings": True,
                "nocheckcertificate": True,
                "retries": 3,
                **opts,
            }
            # 찾은 ffmpeg 경로를 명시적으로 전달
            if self.ffmpeg_path:
                ydl_opts["ffmpeg_location"] = self.ffmpeg_path

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # download=True 로 받으면서 최종 파일 경로도 info에서 수집
                info = ydl.extract_info(url, download=True)

            # 키 조정이 필요하면 받은 파일들에 FFmpeg 피치 시프트 적용
            if semitones != 0:
                paths = collect_filepaths(info)
                for i, path in enumerate(paths, 1):
                    self.after(0, lambda i=i, n=len(paths): self.set_status(
                        f"키 조정 중... ({i}/{n})"))
                    shift_pitch(path, semitones, self.ffmpeg_path)
                    # 원본(키 조정 전) 파일은 삭제하고 조정본만 남긴다
                    try:
                        os.remove(path)
                    except OSError:
                        pass

            # 성공 → 메인 스레드에서 UI 갱신
            self.after(0, self._on_done)
        except Exception as e:
            # 앱이 절대 죽지 않도록 모든 예외를 받아 한국어로 안내
            msg = translate_error(e)
            self.after(0, lambda: self._on_error(msg))


    # ── 기존 파일 키 조정 ──
    def on_shift_existing_click(self):
        if self.busy:
            messagebox.showinfo("안내", "다른 작업이 진행 중이에요. 끝난 뒤 다시 시도해 주세요.")
            return
        semitones = parse_key(self.key_menu.get())
        if semitones == 0:
            messagebox.showinfo(
                "안내", "먼저 '키 조정' 드롭다운에서 올리거나 내릴 반음 수를 선택하세요.\n"
                       "(현재 0 = 변경 없음)")
            return
        if not self.ffmpeg_path:
            messagebox.showerror(
                "FFmpeg 없음",
                "키 조정에는 FFmpeg가 필요한데 찾지 못했습니다.\n"
                "ffmpeg.exe를 프로그램과 같은 폴더에 넣어 주세요. (README 참고)")
            return

        src = filedialog.askopenfilename(
            title="키를 조정할 음원 파일 선택",
            filetypes=[("오디오 파일",
                        "*.mp3 *.m4a *.wav *.opus *.webm *.ogg *.flac"),
                       ("모든 파일", "*.*")])
        if not src:
            return

        # 별도 스레드에서 변환 → GUI 멈춤 방지
        self.busy = True
        self.download_btn.configure(state="disabled")
        self.progress.set(0)
        self.set_status(f"키 조정 중... ({os.path.basename(src)})")
        threading.Thread(
            target=self._shift_existing_worker, args=(src, semitones),
            daemon=True,
        ).start()

    def _shift_existing_worker(self, src: str, semitones: int):
        try:
            out = shift_pitch(src, semitones, self.ffmpeg_path)  # 원본은 보존
            self.after(0, lambda: self._on_shift_done(out))
        except Exception as e:
            msg = translate_error(e)
            self.after(0, lambda: self._on_error(msg))

    def _on_shift_done(self, out_path: str):
        self.busy = False
        self.download_btn.configure(state="normal", text="다운로드")
        self.progress.set(1.0)
        self.set_status(f"키 조정 완료: {os.path.basename(out_path)}")
        messagebox.showinfo(
            "완료", f"키 조정이 끝났습니다.\n\n새 파일:\n{out_path}\n\n(원본 파일은 그대로 보존됩니다)")

    # ── 진행률 훅 (워커 스레드에서 호출됨 → after()로 GUI에 전달) ──
    def _progress_hook(self, d: dict):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0
            speed = d.get("speed")
            eta = d.get("eta")
            speed_txt = f"{speed / 1024 / 1024:.1f} MB/s" if speed else "-"
            eta_txt = f"{int(eta)}초 남음" if eta else "-"
            text = f"다운로드 중... {frac * 100:.1f}%  |  {speed_txt}  |  {eta_txt}"
            self.after(0, lambda: (self.progress.set(frac), self.set_status(text)))
        elif d.get("status") == "finished":
            self.after(0, lambda: (
                self.progress.set(1.0),
                self.set_status("변환/마무리 중... 잠시만요"),
            ))

    # ── 완료 / 실패 처리 (메인 스레드) ──
    def _on_done(self):
        self.busy = False
        self.download_btn.configure(state="normal", text="다운로드")
        self.progress.set(1.0)
        self.set_status("완료. 폴더 열기 버튼으로 확인하세요.")
        messagebox.showinfo("완료", "다운로드가 끝났습니다.")

    def _on_error(self, korean_msg: str):
        self.busy = False
        self.download_btn.configure(state="normal", text="다운로드")
        self.progress.set(0)
        self.set_status("실패 — 아래 안내를 확인하세요.")
        messagebox.showerror("다운로드 실패", korean_msg)


def configure_bundled_model_cache() -> None:
    """풀 exe 에 같이 넣은 Demucs 가중치(HuggingFace 캐시)를 쓰게 한다.
    demucs 를 import 하기 전에 호출해야 한다."""
    bundled = resource_path("hf_home")
    if getattr(sys, "frozen", False) and os.path.isdir(bundled):
        os.environ.setdefault("HF_HOME", bundled)
        os.environ.setdefault("HF_HUB_OFFLINE", "1")


def selftest() -> int:
    """GUI 없이 번들이 멀쩡한지 확인. CI 가 빌드 직후 exe 로 실행한다.
    0 = 정상. 라이트는 ffmpeg 만, 풀은 모델 로드까지 확인."""
    configure_bundled_model_cache()
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("selftest: ffmpeg not found", file=sys.stderr)
        return 1
    from stems_page import stems_available
    if stems_available():
        import torch
        import demucs.api
        from separator import MODEL_NAME, SAMPLE_RATE
        sep = demucs.api.Separator(model=MODEL_NAME, device="cpu", progress=False)
        _, out = sep.separate_tensor(torch.zeros(2, SAMPLE_RATE), SAMPLE_RATE)
        missing = set(sep.model.sources) - set(out)
        if missing:
            print(f"selftest: stems missing {sorted(missing)}", file=sys.stderr)
            return 1
        print(f"selftest: full build ok, stems={list(sep.model.sources)}")
    else:
        print("selftest: lite build ok")
    return 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    configure_bundled_model_cache()
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        # 최후의 방어선: GUI 생성 자체가 실패해도 메시지는 보여준다
        try:
            messagebox.showerror("오류", f"프로그램 실행 중 오류가 발생했습니다.\n{e}")
        except Exception:
            print(f"오류: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
