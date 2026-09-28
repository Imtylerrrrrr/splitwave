# -*- coding: utf-8 -*-
"""곡 보관함(Splitwave 폴더) 관리.
main.py / stems_page.py / tempofollow/app.py 가 공유하는 UI 무관 헬퍼.
GUI(customtkinter, tkinter)나 yt_dlp를 여기서 import하지 않는다. 표준 라이브러리만 쓴다."""

import os
import re
import json
from pathlib import Path
from dataclasses import dataclass


LIBRARY_DIRNAME = "Splitwave"
INDEX_NAME = ".splitwave-index.json"
STEMS_SUFFIX = "_stems"
AUDIO_EXTS = (".m4a", ".mp3", ".wav", ".flac", ".ogg", ".opus", ".webm", ".aac", ".mka", ".mp4")


# ──────────────────────────────────────────────
# 설정 저장 (main.py 29~55행에서 옮겨 옴, 동작 동일)
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
# 보관함 폴더
# ──────────────────────────────────────────────

def base_dir(settings: dict | None = None) -> str:
    """저장 폴더. last_dir 가 실제 폴더면 그것, 아니면 default_download_dir()."""
    if settings is None:
        settings = load_settings()
    last_dir = settings.get("last_dir")
    if last_dir and os.path.isdir(last_dir):
        return last_dir
    return default_download_dir()


def library_dir(base: str) -> str:
    """저장 폴더 아래의 보관함 경로. 폴더 이름이 이미 Splitwave면(대소문자 무시)
    그 폴더 자체를 보관함으로 쓴다. 실제로 만들지는 않는다."""
    name = os.path.basename(os.path.normpath(base))
    if name.lower() == LIBRARY_DIRNAME.lower():
        return base
    return os.path.join(base, LIBRARY_DIRNAME)


def ensure_library(base: str) -> str:
    """library_dir 를 실제로 만들어서 돌려준다."""
    lib = library_dir(base)
    os.makedirs(lib, exist_ok=True)
    return lib


# ──────────────────────────────────────────────
# 목록
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class Track:
    """보관함의 곡 하나 또는 스템 하나."""
    label: str          # 화면 이름: "곡 제목" 또는 "곡 제목 / 건반"
    path: str           # 절대 경로
    song: str           # 곡 이름 (확장자 뺀 파일 이름)
    stem: str | None    # 스템 이름 (확장자 뺀 파일 이름). 곡 자체면 None


def list_songs(lib: str) -> list[Track]:
    """보관함 바로 아래의 곡 파일 목록. 수정 시각 최신순, 같으면 이름순.
    폴더가 없거나 읽을 수 없으면 빈 목록."""
    try:
        names = os.listdir(lib)
    except OSError:
        return []

    items = []
    for name in names:
        if name.startswith("."):
            continue
        if os.path.splitext(name)[1].lower() not in AUDIO_EXTS:
            continue
        path = os.path.join(lib, name)
        if not os.path.isfile(path):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        items.append((mtime, name, path))

    items.sort(key=lambda item: (-item[0], item[1]))
    return [
        Track(label=os.path.splitext(name)[0], path=os.path.abspath(path),
              song=os.path.splitext(name)[0], stem=None)
        for _, name, path in items
    ]


def list_tracks(lib: str) -> list[Track]:
    """곡 단위로 묶은 목록. 묶음 = 곡 파일(있으면) + <곡 이름>_stems/ 바로 아래의
    오디오 파일(이름순). 곡 파일 없이 스템 폴더만 있어도 묶음이 된다.
    묶음 순서는 묶음 안 파일의 수정 시각 중 가장 최근 것 기준 최신순, 같으면 곡 이름순.
    스템 폴더 안에 오디오 파일이 없으면 그 폴더는 무시한다."""
    try:
        names = os.listdir(lib)
    except OSError:
        return []

    song_files = {}   # 곡 이름 -> (경로, 파일 이름)
    stem_dirs = {}    # 곡 이름 -> 스템 폴더 경로

    for name in names:
        if name.startswith("."):
            continue
        path = os.path.join(lib, name)
        if os.path.isfile(path) and os.path.splitext(name)[1].lower() in AUDIO_EXTS:
            song_files[os.path.splitext(name)[0]] = (path, name)
        elif os.path.isdir(path) and name.endswith(STEMS_SUFFIX):
            stem_dirs[name[: -len(STEMS_SUFFIX)]] = path

    bundles = []
    for song in set(song_files) | set(stem_dirs):
        tracks = []
        mtimes = []

        song_entry = song_files.get(song)
        if song_entry:
            song_path, _ = song_entry
            try:
                mtime = os.path.getmtime(song_path)
            except OSError:
                song_entry = None
            else:
                tracks.append(Track(label=song, path=os.path.abspath(song_path),
                                     song=song, stem=None))
                mtimes.append(mtime)

        stem_dir = stem_dirs.get(song)
        if stem_dir:
            try:
                stem_names = os.listdir(stem_dir)
            except OSError:
                stem_names = []
            stem_items = []
            for sname in stem_names:
                if sname.startswith("."):
                    continue
                if os.path.splitext(sname)[1].lower() not in AUDIO_EXTS:
                    continue
                spath = os.path.join(stem_dir, sname)
                if not os.path.isfile(spath):
                    continue
                try:
                    smtime = os.path.getmtime(spath)
                except OSError:
                    continue
                stem_items.append((sname, spath, smtime))
            stem_items.sort(key=lambda item: item[0])
            for sname, spath, smtime in stem_items:
                stem = os.path.splitext(sname)[0]
                tracks.append(Track(label=f"{song} / {stem}", path=os.path.abspath(spath),
                                     song=song, stem=stem))
                mtimes.append(smtime)

        if not tracks:
            continue
        bundles.append((max(mtimes), song, tracks))

    bundles.sort(key=lambda b: (-b[0], b[1]))
    result = []
    for _, _, tracks in bundles:
        result.extend(tracks)
    return result


def menu_labels(tracks: list[Track], max_len: int = 48) -> dict[str, str]:
    """드롭다운에 쓸 {표시 이름: 경로}. 입력 순서를 지킨다. 표시 이름이 max_len 보다
    길면 끝을 ...로 줄인다(줄인 뒤 길이가 max_len). 스템 라벨은 곡 이름 쪽을 줄여서
    " / <스템 이름>" 이 항상 보이게 한다. 표시 이름이 겹치면 두 번째부터 (2), (3) 을 붙인다."""
    result = {}
    seen = {}
    for t in tracks:
        label = t.label
        if len(label) > max_len:
            if t.stem is None:
                label = label[: max_len - 3] + "..."
            else:
                suffix = f" / {t.stem}"
                avail = max(0, max_len - len(suffix) - 3)
                label = t.song[:avail] + "..." + suffix
        seen[label] = seen.get(label, 0) + 1
        n = seen[label]
        key = label if n == 1 else f"{label} ({n})"
        result[key] = t.path
    return result


# ──────────────────────────────────────────────
# 영상 ID / 색인
# ──────────────────────────────────────────────

_YOUTUBE_HOST_RE = re.compile(
    r"^(https?://)?(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE
)
_VIDEO_ID_PATTERNS = (
    re.compile(r"[?&]v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"/shorts/([A-Za-z0-9_-]{11})"),
    re.compile(r"/live/([A-Za-z0-9_-]{11})"),
    re.compile(r"/embed/([A-Za-z0-9_-]{11})"),
)


def video_id(url: str) -> str | None:
    """유튜브 주소에서 영상 ID를 뽑는다. 유튜브 주소가 아니거나 못 찾으면 None."""
    url = url.strip()
    if not _YOUTUBE_HOST_RE.match(url):
        return None
    for pattern in _VIDEO_ID_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def downloads_from_info(info: dict) -> list[tuple[str, list[str]]]:
    """yt-dlp info(재생목록이면 entries)에서 항목마다
    (영상 ID, requested_downloads 의 filepath 중 실제로 있는 파일). id 나 파일이 없는
    항목은 뺀다."""
    result = []
    for e in info.get("entries") or [info]:
        if not e:
            continue
        vid = e.get("id")
        if not vid:
            continue
        paths = [
            rd["filepath"] for rd in (e.get("requested_downloads") or [])
            if rd.get("filepath") and os.path.isfile(rd["filepath"])
        ]
        if not paths:
            continue
        result.append((vid, paths))
    return result


def _read_index(lib: str) -> dict:
    """색인 읽기. 없음/깨짐/형식 다름은 빈 색인으로 취급."""
    try:
        with open(os.path.join(lib, INDEX_NAME), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"version": 1, "videos": {}}
    if not isinstance(data, dict) or not isinstance(data.get("videos"), dict):
        return {"version": 1, "videos": {}}
    return data


def _entry(data: dict, vid: str) -> list[str]:
    """색인에서 영상 하나의 파일 이름들. 형식이 다르면 빈 목록."""
    value = data["videos"].get(vid)
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def _write_index(lib: str, data: dict) -> None:
    """임시 파일 + os.replace 로 쓴다. 실패는 무시(색인은 편의 기능)."""
    path = os.path.join(lib, INDEX_NAME)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def record_download(lib: str, vid: str, paths: list[str]) -> None:
    """보관함 안의 경로만 색인에 기록한다(밖이면 무시). 같은 이름은 한 번만.
    쓰기 실패는 무시한다."""
    lib_abs = os.path.abspath(lib)
    rels = []
    for p in paths:
        try:
            rel = os.path.relpath(os.path.abspath(p), lib_abs)
        except ValueError:
            continue
        if rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
            continue
        rels.append(rel.replace(os.sep, "/"))
    if not rels:
        return

    data = _read_index(lib)
    existing = _entry(data, vid)
    data["videos"][vid] = existing
    for r in rels:
        if r not in existing:
            existing.append(r)
    _write_index(lib, data)


def find_downloaded(lib: str, vid: str) -> list[str]:
    """색인에 있고 지금도 존재하는 파일의 절대 경로."""
    result = []
    for rel in _entry(_read_index(lib), vid):
        path = os.path.join(lib, rel.replace("/", os.sep))
        if os.path.isfile(path):
            result.append(os.path.abspath(path))
    return result
