"""Splitwave Hub 핵심 로직: 매니페스트, 다운로드, 설치, 업데이트, 삭제, 실행. 표준 라이브러리만 쓴다."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence

REPO_URL = "https://github.com/Imtylerrrrrr/splitwave"
NOT_INSTALLED = "not_installed"
UP_TO_DATE = "up_to_date"
UPDATE_AVAILABLE = "update_available"

MSG_NETWORK = "인터넷에 연결하지 못했어요. 연결을 확인하고 다시 시도해 주세요."
MSG_CORRUPT = "받은 파일이 손상됐어요. 다시 시도해 주세요."
MSG_RUNNING = "앱이 실행 중이에요. 앱을 닫고 다시 시도해 주세요."
MSG_SPACE = "디스크 공간이 부족해요. 약 {n} MB가 필요해요."
MSG_FORMAT = "설치 목록 형식이 올바르지 않아요. 허브를 새로 받아 주세요."
MSG_SCHEMA = "이 허브로는 새 목록을 읽을 수 없어요. 허브를 업데이트해 주세요."
MSG_ZIP_PATH = "설치 파일에 허용되지 않는 경로가 있어요."
MSG_NOT_INSTALLED = "설치되지 않은 앱이에요."
MSG_UNKNOWN_APP = "목록에 없는 앱이에요."
MSG_SELF_UPDATE = "허브를 새 버전으로 바꾸지 못했어요. 새 허브를 직접 받아 주세요."

MB = 1024 * 1024
SPACE_MARGIN = 50 * MB
CHUNK = 64 * 1024

_VERSION = re.compile(r"[0-9]+(\.[0-9]+){1,3}")
_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_HEX = re.compile(r"[0-9a-f]{64}")
_DRIVE = re.compile(r"[A-Za-z]:")

Progress = Callable[[int, int, str], None]


class HubError(Exception):
    """str(e) 가 사용자에게 보일 한국어 문구."""


@dataclass(frozen=True)
class Part:
    id: str
    file: str
    size: int
    unpacked: int
    sha256: str
    content: str


@dataclass(frozen=True)
class HubFile:
    file: str
    size: int
    sha256: str


@dataclass(frozen=True)
class AppInfo:
    id: str
    name: str
    description: str
    exe: str
    parts: tuple[Part, ...]


@dataclass(frozen=True)
class Manifest:
    version: str
    hub: HubFile | None
    apps: tuple[AppInfo, ...]

    def app(self, app_id: str) -> AppInfo:
        for a in self.apps:
            if a.id == app_id:
                return a
        raise HubError(MSG_UNKNOWN_APP)


@dataclass(frozen=True)
class Status:
    state: str
    installed_version: str | None
    download_size: int


# ---------- 매니페스트 ----------

def _get(d, key, kind):
    v = d.get(key) if isinstance(d, dict) else None
    ok = {
        "str": isinstance(v, str),
        "posint": isinstance(v, int) and not isinstance(v, bool) and v > 0,
        "list": isinstance(v, list),
    }[kind]
    if not ok:
        raise HubError(MSG_FORMAT)
    return v


def _match(pattern: re.Pattern, d, key) -> str:
    v = _get(d, key, "str")
    if not pattern.fullmatch(v):
        raise HubError(MSG_FORMAT)
    return v


def _check_exe(exe: str) -> str:
    parts = exe.split("/")
    if (not exe or exe.startswith("/") or "\\" in exe or ".." in parts
            or _DRIVE.match(exe) or "" in parts):
        raise HubError(MSG_FORMAT)
    return exe


def parse_manifest(data: bytes | str | dict) -> Manifest:
    if not isinstance(data, dict):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            raise HubError(MSG_FORMAT) from None
    if not isinstance(data, dict):
        raise HubError(MSG_FORMAT)
    schema = data.get("schema")
    if isinstance(schema, int) and not isinstance(schema, bool) and schema > 1:
        raise HubError(MSG_SCHEMA)
    if schema != 1 or isinstance(schema, bool):
        raise HubError(MSG_FORMAT)
    version = _match(_VERSION, data, "version")
    hub = None
    if data.get("hub") is not None:
        h = data["hub"]
        hub = HubFile(_match(_FILE, h, "file"), _get(h, "size", "posint"), _match(_HEX, h, "sha256"))
    apps, app_ids = [], set()
    for a in _get(data, "apps", "list"):
        app_id = _match(_ID, a, "id")
        raw_parts = _get(a, "parts", "list")
        if app_id in app_ids or not raw_parts:
            raise HubError(MSG_FORMAT)
        app_ids.add(app_id)
        parts, part_ids = [], set()
        for p in raw_parts:
            part = Part(_match(_ID, p, "id"), _match(_FILE, p, "file"), _get(p, "size", "posint"),
                        _get(p, "unpacked", "posint"), _match(_HEX, p, "sha256"),
                        _match(_HEX, p, "content"))
            if part.id in part_ids:
                raise HubError(MSG_FORMAT)
            part_ids.add(part.id)
            parts.append(part)
        apps.append(AppInfo(app_id, _get(a, "name", "str"), _get(a, "description", "str"),
                            _check_exe(_get(a, "exe", "str")), tuple(parts)))
    return Manifest(version, hub, tuple(apps))


# ---------- 환경, 주소 ----------

def default_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Splitwave"
    return Path.home() / ".local" / "share" / "Splitwave"


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for k in list(env):
        if k.startswith("_PYI_") or k == "_MEIPASS2":
            del env[k]
    return env


def check_final_url(url: str, https_only: bool) -> None:
    if https_only and not url.lower().startswith("https://"):
        raise HubError(MSG_NETWORK)


class Source:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.https_only = base_url is None

    def manifest_url(self) -> str:
        if self.base_url:
            return f"{self.base_url}/manifest.json"
        return f"{REPO_URL}/releases/latest/download/manifest.json"

    def asset_url(self, version: str, file: str) -> str:
        if self.base_url:
            return f"{self.base_url}/{file}"
        return f"{REPO_URL}/releases/download/v{version}/{file}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


# ---------- zip ----------

def _zip_members(zf: zipfile.ZipFile, dest: Path) -> list[tuple[zipfile.ZipInfo, str]]:
    """전 멤버를 검사해 (멤버, 정규화된 상대 경로) 목록을 돌려준다. 하나라도 위반이면 HubError."""
    base = dest.resolve()
    out = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.endswith("/"):
            continue
        comps = name.split("/")
        is_link = (info.external_attr >> 16) & 0o170000 == 0o120000
        if (not name or name.startswith("/") or _DRIVE.match(name) or ".." in comps or is_link):
            raise HubError(MSG_ZIP_PATH)
        rel = "/".join(c for c in comps if c not in ("", "."))
        if not rel or not (dest / rel).resolve().is_relative_to(base):
            raise HubError(MSG_ZIP_PATH)
        out.append((info, rel))
    return out


# ---------- 허브 ----------

class Hub:
    def __init__(self, root: Path | None = None, source: Source | None = None):
        self.root = Path(root) if root is not None else default_root()
        self.source = source or Source()

    # 기본 경로와 기록

    @property
    def _downloads(self) -> Path:
        return self.root / "downloads"

    def _app_dir(self, app_id: str) -> Path:
        return self.root / "apps" / app_id

    def log(self, msg: str) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with open(self.root / "hub.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
        except OSError:
            pass

    def _load(self) -> dict:
        try:
            state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
            if isinstance(state, dict) and isinstance(state.get("apps"), dict):
                return state
        except (OSError, ValueError):
            pass
        return {"schema": 1, "apps": {}}

    def _save(self, state: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "state.json.tmp"
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.root / "state.json")

    def installed(self) -> dict[str, dict]:
        return copy.deepcopy(self._load()["apps"])

    # 네트워크

    def _open(self, url: str):
        req = urllib.request.Request(url, headers={"User-Agent": "splitwave-hub"})
        resp = urllib.request.urlopen(req, timeout=30)
        try:
            check_final_url(resp.geturl(), self.source.https_only)
        except HubError:
            resp.close()
            raise
        return resp

    def fetch_manifest(self) -> Manifest:
        try:
            with self._open(self.source.manifest_url()) as r:
                data = r.read()
        except OSError:
            raise HubError(MSG_NETWORK) from None
        return parse_manifest(data)

    def _download(self, url: str, dest: Path, size: int, sha256: str, name: str,
                  progress: Progress | None, done: int, total: int) -> int:
        """dest 로 받고 크기와 sha256 을 확인한다. 받은 누적 바이트를 돌려준다."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        h, n = hashlib.sha256(), 0
        try:
            with self._open(url) as r, open(dest, "wb") as f:
                while chunk := r.read(CHUNK):
                    n += len(chunk)
                    if n > size:
                        raise HubError(MSG_CORRUPT)
                    h.update(chunk)
                    f.write(chunk)
                    if progress:
                        progress(done + n, total, name)
            if n != size or h.hexdigest() != sha256:
                raise HubError(MSG_CORRUPT)
        except HubError:
            dest.unlink(missing_ok=True)
            raise
        except OSError:
            dest.unlink(missing_ok=True)
            raise HubError(MSG_NETWORK) from None
        return done + n

    # 상태

    @staticmethod
    def _part_fresh(part: Part, rec: dict | None, app_dir: Path) -> bool:
        return (bool(rec) and rec.get("content") == part.content
                and all((app_dir / f).is_file() for f in rec.get("files", [])))

    def status(self, app: AppInfo) -> Status:
        rec = self._load()["apps"].get(app.id)
        if rec is None:
            return Status(NOT_INSTALLED, None, sum(p.size for p in app.parts))
        saved = rec.get("parts", {})
        stale = [p for p in app.parts if not self._part_fresh(p, saved.get(p.id), self._app_dir(app.id))]
        extra = set(saved) - {p.id for p in app.parts}
        state = UP_TO_DATE if not stale and not extra else UPDATE_AVAILABLE
        return Status(state, rec.get("version"), sum(p.size for p in stale))

    def is_running(self, app_id: str) -> bool:
        if os.name != "nt":
            return False
        rec = self._load()["apps"].get(app_id)
        if not rec:
            return False
        try:
            with open(self._app_dir(app_id) / rec["exe"], "r+b"):
                return False
        except PermissionError:
            return True
        except OSError:
            return False

    # 파일 정리

    def _delete_files(self, app_dir: Path, files: list[str]) -> None:
        base = app_dir.resolve()
        for rel in files:
            path = app_dir / rel
            if path.resolve().is_relative_to(base) and path.is_file():
                path.unlink()

    @staticmethod
    def _prune(app_dir: Path) -> None:
        if not app_dir.is_dir():
            return
        for dirpath, _, _ in os.walk(app_dir, topdown=False):
            if Path(dirpath) != app_dir:
                try:
                    os.rmdir(dirpath)
                except OSError:
                    pass

    def _clear_downloads(self) -> None:
        if self._downloads.is_dir():
            for f in self._downloads.iterdir():
                if f.is_file():
                    f.unlink(missing_ok=True)

    # 설치와 업데이트

    def install(self, manifest: Manifest, app_id: str, progress: Progress | None = None) -> None:
        app = manifest.app(app_id)
        app_dir = self._app_dir(app_id)
        state = self._load()
        saved = state["apps"].get(app_id, {}).get("parts", {})
        todo = [p for p in app.parts if not self._part_fresh(p, saved.get(p.id), app_dir)]
        gone = [pid for pid in saved if pid not in {p.id for p in app.parts}]
        if not todo and not gone:
            return
        if self.is_running(app_id):
            raise HubError(MSG_RUNNING)

        need = sum(p.size + p.unpacked for p in todo) + SPACE_MARGIN
        self.root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.root).free < need:
            raise HubError(MSG_SPACE.format(n=-(-need // MB)))

        # 모든 part 를 받고 검증한 뒤에야 앱 폴더를 건드린다.
        total, done = sum(p.size for p in todo), 0
        try:
            for p in todo:
                dest = self._downloads / f"{p.file}.part"
                done = self._download(self.source.asset_url(manifest.version, p.file), dest,
                                      p.size, p.sha256, p.file, progress, done, total)
                if p.file.lower().endswith(".zip"):
                    try:
                        with zipfile.ZipFile(dest) as zf:
                            _zip_members(zf, app_dir)
                    except zipfile.BadZipFile:
                        raise HubError(MSG_CORRUPT) from None
        except BaseException:
            self._clear_downloads()
            raise
        self.log(f"install {app_id} v{manifest.version}: {', '.join(p.id for p in todo) or '-'}")

        rec = state["apps"].setdefault(app_id, {"name": app.name, "version": None, "exe": app.exe, "parts": {}})
        rec.setdefault("parts", {})
        for p in todo:
            old = rec["parts"].pop(p.id, None)
            self._save(state)
            if old:
                self._delete_files(app_dir, old.get("files", []))
            src = self._downloads / f"{p.file}.part"
            app_dir.mkdir(parents=True, exist_ok=True)
            if p.file.lower().endswith(".zip"):
                files = []
                with zipfile.ZipFile(src) as zf:
                    for info, rel in _zip_members(zf, app_dir):
                        target = app_dir / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as fin, open(target, "wb") as fout:
                            shutil.copyfileobj(fin, fout, CHUNK)
                        files.append(rel)
            else:
                shutil.copyfile(src, app_dir / p.file)
                files = [p.file]
            rec["parts"][p.id] = {"content": p.content, "files": files}
            self._save(state)

        for pid in gone:
            self._delete_files(app_dir, rec["parts"][pid].get("files", []))
            del rec["parts"][pid]
        rec.update(name=app.name, version=manifest.version, exe=app.exe)
        self._save(state)
        self._prune(app_dir)
        self._clear_downloads()

    def remove(self, app_id: str) -> None:
        state = self._load()
        rec = state["apps"].get(app_id)
        if rec is None:
            raise HubError(MSG_NOT_INSTALLED)
        if self.is_running(app_id):
            raise HubError(MSG_RUNNING)
        app_dir = self._app_dir(app_id)
        for part in rec.get("parts", {}).values():
            self._delete_files(app_dir, part.get("files", []))
        self._prune(app_dir)
        try:
            app_dir.rmdir()
        except OSError:
            pass
        del state["apps"][app_id]
        self._save(state)
        self.log(f"remove {app_id}")

    # 실행

    def launch(self, app_id: str, args: Sequence[str] = ()) -> subprocess.Popen:
        rec = self._load()["apps"].get(app_id)
        exe = self._app_dir(app_id) / rec["exe"] if rec else None
        if exe is None or not exe.is_file():
            raise HubError(MSG_NOT_INSTALLED)
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        self.log(f"launch {app_id}")
        return subprocess.Popen([str(exe), *args], cwd=str(exe.parent), env=child_env())

    # 허브 자체 업데이트

    def hub_update_available(self, manifest: Manifest) -> bool:
        if not getattr(sys, "frozen", False) or manifest.hub is None:
            return False
        try:
            return _sha256_file(Path(sys.executable)) != manifest.hub.sha256
        except OSError:
            return False

    def self_update(self, manifest: Manifest, progress: Progress | None = None) -> Path:
        if manifest.hub is None:
            raise HubError(MSG_SELF_UPDATE)
        exe = Path(sys.executable)
        new, old = exe.with_name(exe.name + ".new"), exe.with_name(exe.name + ".old")
        hub = manifest.hub
        self._download(self.source.asset_url(manifest.version, hub.file), new,
                       hub.size, hub.sha256, hub.file, progress, 0, hub.size)
        try:
            old.unlink(missing_ok=True)
            os.replace(exe, old)
            try:
                os.replace(new, exe)
            except OSError:
                os.replace(old, exe)
                raise
        except OSError:
            new.unlink(missing_ok=True)
            self.log("self update failed")
            raise HubError(MSG_SELF_UPDATE) from None
        self.log(f"self update to v{manifest.version}")
        return exe

    def cleanup_old_self(self) -> None:
        if not getattr(sys, "frozen", False):
            return
        exe = Path(sys.executable)
        try:
            exe.with_name(exe.name + ".old").unlink(missing_ok=True)
        except OSError:
            pass
