"""허브용 part 나누기: 앱 zip 하나를 여러 zip 으로 쪼갠다.

풀 버전은 대부분(torch, 모델)이 릴리스마다 바이트 단위로 같고 실행파일 쪽만 바뀐다.
잘 안 바뀌는 것끼리 묶어 두면 허브가 업데이트 때 바뀐 묶음만 받는다.
규칙은 tools/apps.json 의 앱 항목에 있다:

    "split": {"source": "<원본 zip>", "parts": [{"id": "...", "patterns": ["..."]}, ...]}

멤버마다 위에서부터 처음 맞는 part 에 들어간다 (fnmatch, `*` 는 `/` 도 포함).
모든 파일이 정확히 한 part 에 들어가야 하고 빈 part 가 있으면 실패한다.

사용: python tools/split_parts.py --apps tools/apps.json --dir release
"""
import argparse
import fnmatch
import json
import os
import shutil
import zipfile

CHUNK = 1024 * 1024


def assign(names: list, parts: list) -> dict:
    out = {p["id"]: [] for p in parts}
    for name in names:
        for p in parts:
            if any(fnmatch.fnmatchcase(name, pat) for pat in p["patterns"]):
                out[p["id"]].append(name)
                break
        else:
            raise SystemExit(f"split_parts: no part matches {name}. "
                             "Fix: add a pattern in apps.json (the last part usually has \"*\").")
    empty = [pid for pid, files in out.items() if not files]
    if empty:
        raise SystemExit(f"split_parts: part {', '.join(empty)} matched no files. "
                         "Fix: check its patterns in apps.json against the build layout.")
    return out


def split(app: dict, directory: str) -> list:
    """app["split"] 규칙대로 원본 zip 을 나눠 directory 에 쓴다. 만든 파일 이름 목록을 돌려준다."""
    rules = app["split"]["parts"]
    files = {p["id"]: p["file"] for p in app["parts"]}
    if sorted(files) != sorted(p["id"] for p in rules):
        raise SystemExit(f"split_parts: {app['id']} parts and split.parts have different ids. "
                         "Fix: list the same part ids in both.")
    src = os.path.join(directory, app["split"]["source"])
    if not os.path.isfile(src):
        raise SystemExit(f"split_parts: missing {src}. Fix: download the CI artifact into the directory.")
    with zipfile.ZipFile(src) as zin:
        members = {i.filename.replace("\\", "/"): i for i in zin.infolist() if not i.is_dir()}
        groups = assign(sorted(members), rules)
        for pid, names in groups.items():
            dest = os.path.join(directory, files[pid])
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
                for name in names:
                    info = zipfile.ZipInfo(name, date_time=members[name].date_time)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = members[name].external_attr
                    with zin.open(members[name]) as r, zout.open(info, "w", force_zip64=True) as w:
                        shutil.copyfileobj(r, w, CHUNK)
            size = os.path.getsize(dest)
            print(f"split_parts: {files[pid]}: {len(names)} files, {size / 1e6:.1f} MB")
    return [files[pid] for pid in groups]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apps", required=True)
    ap.add_argument("--dir", required=True)
    args = ap.parse_args(argv)
    with open(args.apps, encoding="utf-8") as f:
        apps = json.load(f)
    for app in apps["apps"]:
        if "split" in app:
            split(app, args.dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
