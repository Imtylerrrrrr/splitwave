# -*- coding: utf-8 -*-
"""
유튜브 오디오(MR/반주) 다운로더
- yt-dlp + FFmpeg + customtkinter
- Windows 단일 .exe 패키징(PyInstaller) 대응
"""

import os
import re
import sys
import json
import shutil
import threading
import subprocess
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import yt_dlp


# ──────────────────────────────────────────────
# 경로 / FFmpeg 탐색 (PyInstaller frozen 대응)
# ──────────────────────────────────────────────

def resource_path(relative: str) -> str:
    """PyInstaller로 묶였을 때(sys._MEIPASS)와 일반 실행 모두에서
    리소스의 실제 경로를 돌려준다."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = sys._MEIPASS  # --onefile 실행 시 임시 압축해제 폴더
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)


def app_dir() -> str:
    """실행파일(.exe) 또는 스크립트가 놓인 폴더."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_ffmpeg() -> str | None:
    """ffmpeg 경로를 우선순위대로 탐색:
    (1) PyInstaller 번들 내부(sys._MEIPASS)
    (2) 실행파일/스크립트와 같은 폴더의 ffmpeg.exe
    (3) 시스템 PATH
    """
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

    # (1) 번들 내부
    bundled = resource_path(exe_name)
    if os.path.isfile(bundled):
        return bundled

    # (2) 실행파일 옆
    beside = os.path.join(app_dir(), exe_name)
    if os.path.isfile(beside):
        return beside

    # (3) PATH
    return shutil.which("ffmpeg")


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

FORMAT_HELP = (
    "ℹ️ 유튜브 원본 오디오는 Opus 약 160kbps가 상한이라,\n"
    "MP3 320k나 WAV로 변환해도 실제 음질이 더 좋아지지는 않습니다.\n"
    "• 재인코딩 없음: 진짜 최고 음질 (단 .webm/opus라 일부 프로그램에서 까다로움)\n"
    "• m4a: 음질 거의 동일 + DAW/편집 프로그램 호환성 좋음\n"
    "• MP3 320k: 어디서나 재생되는 호환성 최강\n"
    "• WAV: 편집 편의용 무손실 컨테이너"
)


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
# 키 조정 (피치 시프트, 반음 단위)
# ──────────────────────────────────────────────

# 드롭다운에 보여줄 키 값: +6 ~ -6 반음
KEY_VALUES = ["+6", "+5", "+4", "+3", "+2", "+1", "0 (원본)",
              "-1", "-2", "-3", "-4", "-5", "-6"]

KEY_HELP = "🎹 키 조정: 템포(속도)는 그대로 두고 음높이만 반음 단위로 올리거나 내립니다."


def parse_key(label: str) -> int:
    """드롭다운 라벨 → 반음 정수. '0 (원본)' → 0, '+2' → 2, '-3' → -3."""
    return int(label.split()[0].replace("+", ""))


def pitch_filter(semitones: int) -> str:
    """FFmpeg 오디오 필터 문자열 생성.
    asetrate로 피치를 바꾸면 속도도 같이 바뀌므로,
    atempo로 속도를 역보정해서 '키만' 변경한다."""
    factor = 2 ** (semitones / 12)  # 반음당 2^(1/12)배
    return (f"aresample=48000,"
            f"asetrate={int(48000 * factor)},"
            f"aresample=48000,"
            f"atempo={1 / factor:.6f}")


# 확장자별 재인코딩 코덱 (키 조정은 재인코딩이 필수)
CODEC_BY_EXT = {
    ".mp3":  ["-c:a", "libmp3lame", "-b:a", "320k"],
    ".m4a":  ["-c:a", "aac", "-b:a", "256k"],
    ".wav":  ["-c:a", "pcm_s16le"],
    ".opus": ["-c:a", "libopus", "-b:a", "192k"],
    ".webm": ["-c:a", "libopus", "-b:a", "192k"],
    ".ogg":  ["-c:a", "libopus", "-b:a", "192k"],
    ".flac": ["-c:a", "flac"],
}


def shift_pitch(src: str, semitones: int, ffmpeg: str) -> str:
    """src 파일의 키를 semitones 만큼 조정한 새 파일을 만들어 경로를 돌려준다.
    출력 파일명: '원본이름 (키+2).확장자' 형태."""
    p = Path(src)
    ext = p.suffix.lower()
    codec = CODEC_BY_EXT.get(ext)
    if codec is None:
        # 모르는 확장자는 호환성 좋은 mp3로 출력
        ext = ".mp3"
        codec = CODEC_BY_EXT[".mp3"]

    sign = f"+{semitones}" if semitones > 0 else str(semitones)
    out = p.with_name(f"{p.stem} (키{sign}){ext}")

    cmd = [ffmpeg, "-y", "-i", str(p), "-vn",
           "-af", pitch_filter(semitones), *codec, str(out)]
    # --noconsole 빌드에서 검은 콘솔 창이 뜨지 않도록
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(cmd, capture_output=True, creationflags=flags)

    if result.returncode != 0 or not out.is_file():
        err = result.stderr.decode(errors="replace")[-300:]
        raise RuntimeError(f"키 조정(FFmpeg) 실패: {err}")
    return str(out)


# ──────────────────────────────────────────────
# URL 검사 / 에러 한국어 변환
# ──────────────────────────────────────────────

YOUTUBE_RE = re.compile(
    r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE
)


def is_youtube_url(url: str) -> bool:
    return bool(YOUTUBE_RE.match(url.strip()))


def is_playlist_url(url: str) -> bool:
    """재생목록 파라미터(list=)가 붙은 URL인지 간단 판별."""
    return "list=" in url


def translate_error(err: Exception) -> str:
    """yt-dlp/네트워크 에러를 친절한 한국어 메시지로 변환."""
    msg = str(err)
    low = msg.lower()
    if "sign in to confirm your age" in low or "age" in low and "restrict" in low:
        return "연령 제한이 걸린 영상이라 다운로드할 수 없습니다. (로그인 필요 영상)"
    if "private video" in low or "private" in low:
        return "비공개 영상입니다. 영상 주인만 볼 수 있어요."
    if "video unavailable" in low or "removed" in low or "deleted" in low:
        return "삭제되었거나 더 이상 볼 수 없는 영상입니다."
    if "not available in your country" in low or "geo" in low and "block" in low:
        return "지역 제한으로 현재 국가에서는 받을 수 없는 영상입니다."
    if "copyright" in low:
        return "저작권 문제로 차단된 영상입니다."
    if ("urlopen" in low or "getaddrinfo" in low or "timed out" in low
            or "connection" in low or "network" in low or "ssl" in low):
        return "네트워크 오류가 발생했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요."
    if "unsupported url" in low or "is not a valid url" in low:
        return "지원하지 않는 주소입니다. 유튜브 영상 링크인지 확인해 주세요."
    if "ffmpeg" in low:
        return ("FFmpeg를 찾지 못해 변환에 실패했습니다.\n"
                "ffmpeg.exe를 프로그램과 같은 폴더에 넣어 주세요. (README 참고)")
    # 그 외: 원문 사유를 같이 보여줘서 검색이라도 가능하게
    return f"다운로드에 실패했습니다.\n사유: {msg[:300]}"


# ──────────────────────────────────────────────
# GUI 앱
# ──────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")  # 다크모드 기본
        ctk.set_default_color_theme("blue")

        self.title("유튜브 오디오 다운로더")
        self.geometry("560x700")
        self.resizable(False, False)

        # 상태
        self.settings = load_settings()
        self.save_dir = self.settings.get("last_dir") or default_download_dir()
        if not os.path.isdir(self.save_dir):
            self.save_dir = default_download_dir()
        self.ffmpeg_path = find_ffmpeg()
        self.downloading = False

        self._build_ui()

        # FFmpeg 미발견 시 미리 경고 (변환 포맷 선택 시 필요)
        if not self.ffmpeg_path:
            self.set_status(
                "⚠️ ffmpeg.exe를 찾지 못했습니다. MP3/WAV 변환은 불가능합니다. (README 참고)"
            )

    # ── UI 구성 ──
    def _build_ui(self):
        pad = {"padx": 20, "pady": (10, 0)}

        ctk.CTkLabel(
            self, text="🎵 유튜브 오디오 다운로더",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(**pad)

        # URL 입력
        ctk.CTkLabel(self, text="유튜브 링크를 붙여넣으세요:", anchor="w").pack(
            fill="x", **pad)
        self.url_entry = ctk.CTkEntry(
            self, placeholder_text="https://www.youtube.com/watch?v=...")
        self.url_entry.pack(fill="x", padx=20, pady=(4, 0))

        # 포맷 드롭다운 + 안내문
        ctk.CTkLabel(self, text="출력 포맷 / 품질:", anchor="w").pack(fill="x", **pad)
        self.format_menu = ctk.CTkOptionMenu(self, values=FORMAT_LABELS)
        self.format_menu.set(FORMAT_LABELS[1])  # 기본값: m4a (아이폰 등 호환성 좋음)
        self.format_menu.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkLabel(
            self, text=FORMAT_HELP, justify="left", anchor="w",
            font=ctk.CTkFont(size=11), text_color="gray70",
        ).pack(fill="x", padx=20, pady=(4, 0))

        # 키 조정 드롭다운 + 기존 파일 키 조정 버튼
        key_row = ctk.CTkFrame(self, fg_color="transparent")
        key_row.pack(fill="x", padx=20, pady=(10, 0))
        ctk.CTkLabel(key_row, text="키 조정 (반음):").pack(side="left")
        self.key_menu = ctk.CTkOptionMenu(key_row, values=KEY_VALUES, width=110)
        self.key_menu.set("0 (원본)")  # 기본값: 키 변경 없음
        self.key_menu.pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            key_row, text="🎹 기존 파일 키 조정", width=160,
            fg_color="gray30", hover_color="gray25",
            command=self.on_shift_existing_click,
        ).pack(side="right")
        ctk.CTkLabel(
            self, text=KEY_HELP, justify="left", anchor="w",
            font=ctk.CTkFont(size=11), text_color="gray70",
        ).pack(fill="x", padx=20, pady=(4, 0))

        # 저장 폴더
        folder_row = ctk.CTkFrame(self, fg_color="transparent")
        folder_row.pack(fill="x", padx=20, pady=(10, 0))
        ctk.CTkButton(
            folder_row, text="📁 저장 폴더 선택", width=130,
            command=self.choose_folder,
        ).pack(side="left")
        self.folder_label = ctk.CTkLabel(
            folder_row, text=self.save_dir, anchor="w",
            font=ctk.CTkFont(size=11), text_color="gray70",
        )
        self.folder_label.pack(side="left", padx=(10, 0), fill="x", expand=True)

        # 다운로드 버튼
        self.download_btn = ctk.CTkButton(
            self, text="⬇️ 다운로드", height=40,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.on_download_click,
        )
        self.download_btn.pack(fill="x", padx=20, pady=(14, 0))

        # 진행률
        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=20, pady=(14, 0))
        self.status_label = ctk.CTkLabel(self, text="대기 중", anchor="w")
        self.status_label.pack(fill="x", padx=20, pady=(6, 0))

        # 폴더 열기
        self.open_btn = ctk.CTkButton(
            self, text="📂 폴더 열기", command=self.open_folder,
            fg_color="gray30", hover_color="gray25",
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

    def open_folder(self):
        """저장 폴더를 OS 탐색기로 연다."""
        try:
            if os.name == "nt":
                os.startfile(self.save_dir)  # Windows
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.save_dir])
            else:
                subprocess.Popen(["xdg-open", self.save_dir])
        except Exception:
            messagebox.showinfo("안내", f"폴더 위치: {self.save_dir}")

    # ── 다운로드 시작 ──
    def on_download_click(self):
        if self.downloading:
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
        self.downloading = True
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
                paths = self._collect_filepaths(info)
                for i, path in enumerate(paths, 1):
                    self.after(0, lambda i=i, n=len(paths): self.set_status(
                        f"🎹 키 조정 중... ({i}/{n})"))
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
            self.after(0, lambda: self._on_error(translate_error(e)))

    @staticmethod
    def _collect_filepaths(info: dict) -> list[str]:
        """yt-dlp info dict에서 최종 저장된 파일 경로들을 모은다.
        (postprocessor 변환 후 경로 포함, 재생목록이면 전체 항목)"""
        paths = []
        entries = info.get("entries") or [info]
        for e in entries:
            if not e:
                continue
            for rd in e.get("requested_downloads") or []:
                fp = rd.get("filepath")
                if fp and os.path.isfile(fp):
                    paths.append(fp)
        return paths

    # ── 기존 파일 키 조정 ──
    def on_shift_existing_click(self):
        if self.downloading:
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
        self.downloading = True
        self.download_btn.configure(state="disabled")
        self.progress.set(0)
        self.set_status(f"🎹 키 조정 중... ({os.path.basename(src)})")
        threading.Thread(
            target=self._shift_existing_worker, args=(src, semitones),
            daemon=True,
        ).start()

    def _shift_existing_worker(self, src: str, semitones: int):
        try:
            out = shift_pitch(src, semitones, self.ffmpeg_path)  # 원본은 보존
            self.after(0, lambda: self._on_shift_done(out))
        except Exception as e:
            self.after(0, lambda: self._on_error(translate_error(e)))

    def _on_shift_done(self, out_path: str):
        self.downloading = False
        self.download_btn.configure(state="normal", text="⬇️ 다운로드")
        self.progress.set(1.0)
        self.set_status(f"✅ 키 조정 완료: {os.path.basename(out_path)}")
        messagebox.showinfo(
            "완료", f"키 조정이 끝났습니다! 🎹\n\n새 파일:\n{out_path}\n\n(원본 파일은 그대로 보존됩니다)")

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
        self.downloading = False
        self.download_btn.configure(state="normal", text="⬇️ 다운로드")
        self.progress.set(1.0)
        self.set_status("✅ 완료! 폴더 열기 버튼으로 확인하세요.")
        messagebox.showinfo("완료", "다운로드가 끝났습니다! 🎉")

    def _on_error(self, korean_msg: str):
        self.downloading = False
        self.download_btn.configure(state="normal", text="⬇️ 다운로드")
        self.progress.set(0)
        self.set_status("❌ 실패 — 아래 안내를 확인하세요.")
        messagebox.showerror("다운로드 실패", korean_msg)


def main():
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
