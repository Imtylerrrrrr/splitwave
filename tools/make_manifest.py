"""릴리스 자산으로 manifest.json (schema 1) 을 만든다.

spec: docs/superpowers/specs/2026-09-28-hub-design.md "매니페스트 (schema 1)".
`content` 는 무결성용 `sha256` 과 별개로 내용 동일성 판단용 해시다:
zip 은 디렉터리 항목을 뺀 멤버를 경로순으로 정렬해 "{경로}\0{멤버 sha256 hex}\n" 을
이어 붙인 UTF-8 바이트의 sha256, 일반 파일은 파일의 sha256 과 같다.
200 MB 급 zip 도 통째로 메모리에 올리지 않도록 1 MiB 씩 읽는다.

사용: python tools/make_manifest.py --version 1.1.0 --apps tools/apps.json --dir release
"""
import argparse
import hashlib
import json
import os
import re
import zipfile

CHUNK = 1024 * 1024
_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,3}$")


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _zip_members(zf: zipfile.ZipFile):
    """디렉터리 항목을 뺀 (경로, ZipInfo) 목록. 경로는 \\ 를 / 로 바꾼 것."""
    out = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.endswith("/") or info.is_dir():
            continue
        out.append((name, info))
    return out


def content_hash(path: str) -> str:
    """spec 의 content 정의. zip 이면 멤버 내용 해시, 아니면 파일 sha256."""
    if not path.endswith(".zip"):
        return _sha256_file(path)
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as zf:
        members = sorted(_zip_members(zf), key=lambda t: t[0])
        for name, info in members:
            member_digest = hashlib.sha256()
            with zf.open(info) as mf:
                while True:
                    chunk = mf.read(CHUNK)
                    if not chunk:
                        break
                    member_digest.update(chunk)
            digest.update(f"{name}\0{member_digest.hexdigest()}\n".encode("utf-8"))
    return digest.hexdigest()


def unpacked_size(path: str) -> int:
    if not path.endswith(".zip"):
        return os.path.getsize(path)
    with zipfile.ZipFile(path) as zf:
        return sum(info.file_size for _name, info in _zip_members(zf))


def part_files(path: str) -> list[str]:
    """zip 이면 디렉터리 제외 멤버 경로(\\ 는 / 로), 아니면 [파일 이름]."""
    if not path.endswith(".zip"):
        return [os.path.basename(path)]
    with zipfile.ZipFile(path) as zf:
        return [name for name, _info in _zip_members(zf)]


def _require_file(path: str) -> None:
    if not os.path.isfile(path):
        raise SystemExit(f"make_manifest: missing {path}. Fix: download the CI artifact into the directory.")


_HUB_CORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hub", "core.py")
_HUB_VERSION_RE = re.compile(r'^HUB_VERSION = "([^"]+)"', re.MULTILINE)


def hub_version(path: str = _HUB_CORE) -> str:
    """hub/core.py 의 HUB_VERSION. 허브는 이 값이 자기 것과 다를 때만 자체 업데이트를 권한다."""
    try:
        with open(path, encoding="utf-8") as f:
            found = _HUB_VERSION_RE.search(f.read())
    except OSError:
        found = None
    if not found or not _VERSION_RE.match(found.group(1)):
        raise SystemExit(f"make_manifest: no valid HUB_VERSION in {path}. "
                         'Fix: keep a line like HUB_VERSION = "1.2.0" in hub/core.py.')
    return found.group(1)


def build_manifest(version: str, apps_def: dict, directory: str) -> dict:
    if not _VERSION_RE.match(version):
        raise SystemExit(f"make_manifest: invalid version {version!r}. Fix: use digits and dots like 1.1.0.")

    hub_file = apps_def["hub"]
    hub_path = os.path.join(directory, hub_file)
    _require_file(hub_path)
    hub_entry = {"file": hub_file, "size": os.path.getsize(hub_path), "sha256": _sha256_file(hub_path),
                 "version": hub_version()}

    apps = []
    for app in apps_def["apps"]:
        seen: dict[str, str] = {}
        parts = []
        for part in app["parts"]:
            part_path = os.path.join(directory, part["file"])
            _require_file(part_path)
            for f in part_files(part_path):
                if f in seen:
                    raise SystemExit(
                        f"make_manifest: {app['id']}: path {f} appears in both part "
                        f"{seen[f]!r} and {part['id']!r}. Fix: split parts so their files don't overlap.")
                seen[f] = part["id"]
            parts.append({
                "id": part["id"],
                "file": part["file"],
                "size": os.path.getsize(part_path),
                "unpacked": unpacked_size(part_path),
                "sha256": _sha256_file(part_path),
                "content": content_hash(part_path),
            })
        if app["exe"] not in seen:
            raise SystemExit(
                f"make_manifest: {app['id']}: exe {app['exe']} is not produced by any part. "
                "Fix: check apps.json exe/parts for this app.")
        apps.append({
            "id": app["id"],
            "name": app["name"],
            "description": app["description"],
            "exe": app["exe"],
            "parts": parts,
        })

    return {"schema": 1, "version": version, "hub": hub_entry, "apps": apps}


def write_sums(directory: str) -> None:
    """SHA256SUMS.txt: "<sha256>  <이름>" 이름순, 자기 자신 제외, manifest.json 포함."""
    out_name = "SHA256SUMS.txt"
    names = sorted(
        name for name in os.listdir(directory)
        if name != out_name and os.path.isfile(os.path.join(directory, name)))
    lines = [f"{_sha256_file(os.path.join(directory, name))}  {name}\n" for name in names]
    with open(os.path.join(directory, out_name), "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--apps", required=True)
    parser.add_argument("--dir", required=True)
    args = parser.parse_args(argv)

    with open(args.apps, encoding="utf-8") as f:
        apps_def = json.load(f)

    manifest = build_manifest(args.version, apps_def, args.dir)

    with open(os.path.join(args.dir, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    write_sums(args.dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
