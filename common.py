# -*- coding: utf-8 -*-
"""main.py / stems_page.py / separator.py 가 공유하는 UI 무관 헬퍼.
GUI(customtkinter)나 yt_dlp를 여기서 import하지 않는다."""

import os
import re
import sys
import shutil
import subprocess
from pathlib import Path
from tkinter import messagebox


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
# 키 조정 (피치 시프트, 반음 단위)
# ──────────────────────────────────────────────

# 드롭다운에 보여줄 키 값: +6 ~ -6 반음
KEY_VALUES = ["+6", "+5", "+4", "+3", "+2", "+1", "0 (원본)",
              "-1", "-2", "-3", "-4", "-5", "-6"]

KEY_HELP = "키 조정: 템포(속도)는 그대로 두고 음높이만 반음 단위로 올리거나 내립니다."


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


def collect_filepaths(info: dict) -> list[str]:
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


def open_path(path: str) -> None:
    """폴더를 OS 탐색기로 연다."""
    try:
        if os.name == "nt":
            os.startfile(path)  # Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        messagebox.showinfo("안내", f"폴더 위치: {path}")
