import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("split_parts", ROOT / "tools" / "split_parts.py")
split_parts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(split_parts)

PARTS = [
    {"id": "big", "patterns": ["app/_internal/big/*"]},
    {"id": "code", "patterns": ["app/app.exe", "app/_internal/*.dist-info/*"]},
    {"id": "rest", "patterns": ["*"]},
]


def make_zip(path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("app/", b"")                       # 디렉터리 항목은 무시돼야 한다
        for name, data in files.items():
            z.writestr(name, data)


def members(path):
    with zipfile.ZipFile(path) as z:
        return {i.filename: z.read(i) for i in z.infolist() if not i.is_dir()}


def test_assign_first_match_wins():
    names = ["app/app.exe", "app/_internal/big/a.dll", "app/_internal/big/sub/b.py",
             "app/_internal/big-1.0.dist-info/RECORD", "app/_internal/python312.dll"]
    got = split_parts.assign(names, PARTS)
    assert got == {"big": ["app/_internal/big/a.dll", "app/_internal/big/sub/b.py"],
                   "code": ["app/app.exe", "app/_internal/big-1.0.dist-info/RECORD"],
                   "rest": ["app/_internal/python312.dll"]}


def test_assign_fails_when_a_file_matches_nothing():
    with pytest.raises(SystemExit) as e:
        split_parts.assign(["app/x"], PARTS[:2])
    assert "Fix:" in str(e.value)


def test_assign_fails_when_a_part_is_empty():
    with pytest.raises(SystemExit) as e:
        split_parts.assign(["app/app.exe", "app/other"], PARTS)      # big 에 해당하는 파일이 없다
    assert "big" in str(e.value) and "Fix:" in str(e.value)


def test_split_keeps_every_file_exactly_once(tmp_path):
    files = {"app/app.exe": b"MZ" * 1000, "app/_internal/big/a.dll": b"A" * 5000,
             "app/_internal/big/sub/b.py": b"print(1)\n", "app/_internal/x-1.dist-info/RECORD": b"r",
             "app/_internal/python312.dll": b"P" * 3000}
    make_zip(tmp_path / "app.zip", files)
    app = {"id": "app", "split": {"source": "app.zip", "parts": PARTS},
           "parts": [{"id": "big", "file": "app-big.zip"}, {"id": "code", "file": "app-code.zip"},
                     {"id": "rest", "file": "app-rest.zip"}]}
    out = split_parts.split(app, str(tmp_path))
    assert sorted(out) == ["app-big.zip", "app-code.zip", "app-rest.zip"]
    merged = {}
    for name in out:
        part = members(tmp_path / name)
        assert not set(part) & set(merged)            # 겹치는 경로 없음
        merged.update(part)
    assert merged == files
    assert set(members(tmp_path / "app-big.zip")) == {"app/_internal/big/a.dll", "app/_internal/big/sub/b.py"}


def test_split_requires_matching_part_ids(tmp_path):
    make_zip(tmp_path / "app.zip", {"app/app.exe": b"x", "app/_internal/big/a": b"y", "app/z": b"z"})
    app = {"id": "app", "split": {"source": "app.zip", "parts": PARTS},
           "parts": [{"id": "big", "file": "app-big.zip"}]}
    with pytest.raises(SystemExit) as e:
        split_parts.split(app, str(tmp_path))
    assert "Fix:" in str(e.value)


def test_repo_rules_put_real_layout_in_expected_parts():
    apps = json.loads((ROOT / "tools" / "apps.json").read_text(encoding="utf-8"))
    full = next(a for a in apps["apps"] if a["id"] == "splitwave-full")
    names = ["splitwave-full/splitwave-full.exe",
             "splitwave-full/_internal/base_library.zip",
             "splitwave-full/_internal/torch-2.14.0.dist-info/RECORD",
             "splitwave-full/_internal/numpy-2.5.3.dist-info/RECORD",
             "splitwave-full/_internal/torch/lib/torch_cpu.dll",
             "splitwave-full/_internal/torch/nn/functional.py",
             "splitwave-full/_internal/numpy/_core/_multiarray_umath.cp312-win_amd64.pyd",
             "splitwave-full/_internal/numpy.libs/libscipy_openblas64_.dll",
             "splitwave-full/_internal/hf_home/hub/models--x/snapshots/r/w.safetensors",
             "splitwave-full/_internal/python312.dll",
             "splitwave-full/_internal/ffmpeg.exe"]
    got = split_parts.assign(names, full["split"]["parts"])
    assert got["torch"] == names[4:8]
    assert got["model"] == names[8:9]
    assert got["app"] == names[0:4]           # 빌드마다 바뀌는 파일: 실행파일, base_library, 설치 기록
    assert got["runtime"] == names[9:11]
    assert [p["id"] for p in full["parts"]] == [p["id"] for p in full["split"]["parts"]]
