import hashlib
import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "make_manifest", Path(__file__).resolve().parents[1] / "tools" / "make_manifest.py")
make_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(make_manifest)


def make_zip(path: Path, members: dict, date_time=(2020, 1, 1, 0, 0, 0)) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=date_time)
            zf.writestr(info, data)


def test_content_hash_zip_stable_across_regeneration_but_not_content(tmp_path):
    zip1 = tmp_path / "a.zip"
    zip2 = tmp_path / "b.zip"
    zip3 = tmp_path / "c.zip"
    # 같은 내용, 멤버 순서와 타임스탬프만 다름
    make_zip(zip1, {"a.txt": b"hello", "sub/b.txt": b"world"}, date_time=(2020, 1, 1, 0, 0, 0))
    make_zip(zip2, {"sub/b.txt": b"world", "a.txt": b"hello"}, date_time=(2023, 5, 6, 7, 8, 9))
    # 한 바이트만 다른 내용
    make_zip(zip3, {"a.txt": b"hellO", "sub/b.txt": b"world"}, date_time=(2020, 1, 1, 0, 0, 0))

    h1 = make_manifest.content_hash(str(zip1))
    h2 = make_manifest.content_hash(str(zip2))
    h3 = make_manifest.content_hash(str(zip3))

    assert h1 == h2
    assert h1 != h3
    assert re.fullmatch(r"[0-9a-f]{64}", h1)


def test_content_hash_regular_file_equals_sha256(tmp_path):
    path = tmp_path / "asset.bin"
    data = b"\x00\x01binary-ish-content" * 1000
    path.write_bytes(data)

    assert make_manifest.content_hash(str(path)) == hashlib.sha256(data).hexdigest()


def test_build_manifest_fields_and_values(tmp_path):
    hub_bytes = b"hub-exe-bytes"
    (tmp_path / "splitwave-hub.exe").write_bytes(hub_bytes)
    app_bytes = b"app-exe-bytes" * 10
    (tmp_path / "splitwave.exe").write_bytes(app_bytes)

    apps_def = {
        "hub": "splitwave-hub.exe",
        "apps": [
            {"id": "splitwave", "name": "Splitwave", "description": "설명",
             "exe": "splitwave.exe", "parts": [{"id": "app", "file": "splitwave.exe"}]},
        ],
    }

    manifest = make_manifest.build_manifest("1.1.0", apps_def, str(tmp_path))

    assert manifest["schema"] == 1
    assert manifest["version"] == "1.1.0"
    assert manifest["hub"] == {
        "file": "splitwave-hub.exe",
        "size": len(hub_bytes),
        "sha256": hashlib.sha256(hub_bytes).hexdigest(),
    }
    assert len(manifest["apps"]) == 1
    app = manifest["apps"][0]
    assert app["id"] == "splitwave"
    assert app["name"] == "Splitwave"
    assert app["description"] == "설명"
    assert app["exe"] == "splitwave.exe"
    assert app["parts"] == [{
        "id": "app",
        "file": "splitwave.exe",
        "size": len(app_bytes),
        "unpacked": len(app_bytes),
        "sha256": hashlib.sha256(app_bytes).hexdigest(),
        "content": hashlib.sha256(app_bytes).hexdigest(),
    }]


def test_build_manifest_rejects_overlapping_part_paths(tmp_path):
    (tmp_path / "splitwave-hub.exe").write_bytes(b"hub")
    (tmp_path / "x.txt").write_bytes(b"one")
    make_zip(tmp_path / "bundle.zip", {"x.txt": b"two"})

    apps_def = {
        "hub": "splitwave-hub.exe",
        "apps": [
            {"id": "app1", "name": "App1", "description": "d",
             "exe": "x.txt", "parts": [
                 {"id": "a", "file": "x.txt"},
                 {"id": "b", "file": "bundle.zip"},
             ]},
        ],
    }

    with pytest.raises(SystemExit):
        make_manifest.build_manifest("1.0.0", apps_def, str(tmp_path))


def test_build_manifest_rejects_exe_missing_from_parts(tmp_path):
    (tmp_path / "splitwave-hub.exe").write_bytes(b"hub")
    (tmp_path / "app.exe").write_bytes(b"app")

    apps_def = {
        "hub": "splitwave-hub.exe",
        "apps": [
            {"id": "app1", "name": "App1", "description": "d",
             "exe": "nope.exe", "parts": [{"id": "app", "file": "app.exe"}]},
        ],
    }

    with pytest.raises(SystemExit):
        make_manifest.build_manifest("1.0.0", apps_def, str(tmp_path))


def test_build_manifest_missing_asset_raises_with_fix_hint(tmp_path):
    apps_def = {"hub": "splitwave-hub.exe", "apps": []}

    with pytest.raises(SystemExit) as excinfo:
        make_manifest.build_manifest("1.0.0", apps_def, str(tmp_path))

    assert "Fix:" in str(excinfo.value)


def test_write_sums_format_and_self_exclusion(tmp_path):
    manifest_bytes = b'{"schema": 1}'
    asset_bytes = b"asset-bytes"
    (tmp_path / "manifest.json").write_bytes(manifest_bytes)
    (tmp_path / "asset.bin").write_bytes(asset_bytes)

    make_manifest.write_sums(str(tmp_path))

    sums_path = tmp_path / "SHA256SUMS.txt"
    lines = sums_path.read_text(encoding="utf-8").splitlines()
    assert lines == [
        f"{hashlib.sha256(asset_bytes).hexdigest()}  asset.bin",
        f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json",
    ]
    assert not any(line.endswith("SHA256SUMS.txt") for line in lines)


def test_repo_apps_json_has_three_apps():
    apps_path = Path(__file__).resolve().parents[1] / "tools" / "apps.json"
    with open(apps_path, encoding="utf-8") as f:
        apps_def = json.load(f)

    ids = [app["id"] for app in apps_def["apps"]]
    assert len(ids) == 3
    assert set(ids) == {"splitwave", "splitwave-full", "tempofollow"}


def test_outputs_use_lf_line_endings_on_every_platform(tmp_path, monkeypatch):
    """Windows 러너에서 만들어도 줄바꿈은 LF. CRLF 면 `shasum -c` 가 파일 이름 끝의 \\r 때문에 파일을 못 찾는다."""
    (tmp_path / "a.bin").write_bytes(b"a")
    (tmp_path / "b.bin").write_bytes(b"b")
    import io
    real_open = open

    def windows_like_open(file, mode="r", *a, **k):
        # 텍스트 쓰기에서 newline 을 지정하지 않으면 Windows 처럼 \n 을 \r\n 으로 바꾼다
        if "w" in mode and "b" not in mode and k.get("newline") is None:
            k["newline"] = "\r\n"
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(make_manifest, "open", windows_like_open, raising=False)
    make_manifest.write_sums(str(tmp_path))
    data = (tmp_path / "SHA256SUMS.txt").read_bytes()
    assert b"\r" not in data and data.count(b"\n") == 2
