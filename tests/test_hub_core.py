import functools
import hashlib
import io
import json
import os
import shutil
import socket
import sys
import threading
import types
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hub import core
from hub.core import (NOT_INSTALLED, REPO_URL, UP_TO_DATE, UPDATE_AVAILABLE, Hub, HubError,
                      Source, check_final_url, child_env, parse_manifest)

H = "0" * 64


def sha(b):
    return hashlib.sha256(b).hexdigest()


def zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def zip_content(members):
    """spec 정의: 디렉터리 항목을 뺀 멤버를 경로순으로 정렬해 "{경로}\\0{sha256}\\n" 을 이어 붙인 것의 sha256."""
    items = sorted((n, d) for n, d in members.items() if not n.endswith("/"))
    return sha("".join(f"{n}\0{sha(d)}\n" for n, d in items).encode("utf-8"))


class Server:
    def __init__(self, directory):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.requests = []
        srv = self

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                srv.requests.append(self.path)
                super().do_GET()

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(directory)))
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def part(self, pid, file, payload):
        """payload 가 dict 이면 zip 멤버, bytes 이면 일반 파일."""
        data = zip_bytes(payload) if isinstance(payload, dict) else payload
        (self.dir / file).write_bytes(data)
        if isinstance(payload, dict):
            content, unpacked = zip_content(payload), sum(len(v) for v in payload.values())
        else:
            content, unpacked = sha(data), len(data)
        return {"id": pid, "file": file, "size": len(data), "unpacked": unpacked,
                "sha256": sha(data), "content": content}

    def publish(self, parts, version="1.0.0", exe="demo.exe", hub=None):
        m = {"schema": 1, "version": version,
             "apps": [{"id": "demo", "name": "Demo", "description": "시험 앱", "exe": exe, "parts": parts}]}
        if hub:
            m["self_update"] = hub
        (self.dir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        self.requests.clear()
        return m


@pytest.fixture
def srv(tmp_path):
    s = Server(tmp_path / "srv")
    yield s
    s.httpd.shutdown()
    s.httpd.server_close()


@pytest.fixture
def hub(tmp_path, srv):
    return Hub(tmp_path / "root", Source(srv.base))


def app_dir(hub):
    return hub.root / "apps" / "demo"


def listing(d):
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()) if d.exists() else []


BASE_MEMBERS = {"demo.exe": b"exe-v1", "lib/a.dll": b"a-v1", "lib/b.dll": b"b-v1"}


def install_two(hub, srv):
    parts = [srv.part("app", "app.zip", BASE_MEMBERS), srv.part("data", "data.bin", b"data-v1")]
    srv.publish(parts)
    m = hub.fetch_manifest()
    hub.install(m, "demo")
    return parts


# 1. parse_manifest

def good_manifest():
    return {"schema": 1, "version": "1.1.0",
            "self_update": {"file": "splitwave-hub.exe", "size": 10, "sha256": H},
            "apps": [{"id": "splitwave", "name": "Splitwave", "description": "d", "exe": "sub/splitwave.exe",
                      "parts": [{"id": "app", "file": "splitwave.zip", "size": 5, "unpacked": 9,
                                 "sha256": H, "content": "a" * 64}]}]}


def test_parse_manifest_ok():
    m = parse_manifest(json.dumps(good_manifest()).encode())
    assert m.version == "1.1.0"
    assert m.hub == core.HubFile("splitwave-hub.exe", 10, H)
    app = m.app("splitwave")
    assert app.exe == "sub/splitwave.exe"
    assert app.parts == (core.Part("app", "splitwave.zip", 5, 9, H, "a" * 64),)
    assert parse_manifest(json.dumps(good_manifest())) == m
    assert parse_manifest(good_manifest()) == m
    with pytest.raises(HubError, match="^목록에 없는 앱이에요.$"):
        m.app("nope")


def _set(path, value):
    def mutate(m):
        target = m
        for k in path[:-1]:
            target = target[k]
        if value is DEL:
            del target[path[-1]]
        else:
            target[path[-1]] = value
    return mutate


DEL = object()
APP = ("apps", 0)
PART = ("apps", 0, "parts", 0)

BAD_CASES = {
    "schema missing": _set(("schema",), DEL),
    "schema 0": _set(("schema",), 0),
    "schema str": _set(("schema",), "1"),
    "version missing": _set(("version",), DEL),
    "version one number": _set(("version",), "1"),
    "version prefix v": _set(("version",), "v1.0"),
    "version five numbers": _set(("version",), "1.2.3.4.5"),
    "version trailing newline": _set(("version",), "1.0\n"),
    "app id upper": _set(APP + ("id",), "Splitwave"),
    "app id leading dash": _set(APP + ("id",), "-a"),
    "part id underscore": _set(PART + ("id",), "a_b"),
    "file with slash": _set(PART + ("file",), "a/b.zip"),
    "file with backslash": _set(PART + ("file",), "a\\b.zip"),
    "file leading dot": _set(PART + ("file",), ".zip"),
    "sha256 short": _set(PART + ("sha256",), "0" * 63),
    "sha256 upper": _set(PART + ("sha256",), "A" * 64),
    "content bad": _set(PART + ("content",), "g" * 64),
    "size zero": _set(PART + ("size",), 0),
    "size negative": _set(PART + ("size",), -1),
    "size str": _set(PART + ("size",), "5"),
    "size bool": _set(PART + ("size",), True),
    "size float": _set(PART + ("size",), 5.0),
    "unpacked zero": _set(PART + ("unpacked",), 0),
    "exe absolute": _set(APP + ("exe",), "/x.exe"),
    "exe backslash": _set(APP + ("exe",), "a\\x.exe"),
    "exe dotdot": _set(APP + ("exe",), "../x.exe"),
    "exe inner dotdot": _set(APP + ("exe",), "a/../x.exe"),
    "exe drive": _set(APP + ("exe",), "C:/x.exe"),
    "no parts": _set(APP + ("parts",), []),
    "hub sha bad": _set(("self_update", "sha256"), "x"),
    "hub size zero": _set(("self_update", "size"), 0),
    "apps not list": _set(("apps",), {}),
    "dup app id": lambda m: m["apps"].append(json.loads(json.dumps(m["apps"][0]))),
    "dup part id": lambda m: m["apps"][0]["parts"].append(dict(m["apps"][0]["parts"][0])),
}


@pytest.mark.parametrize("case", list(BAD_CASES))
def test_parse_manifest_rejects(case):
    m = good_manifest()
    BAD_CASES[case](m)
    with pytest.raises(HubError) as e:
        parse_manifest(m)
    assert str(e.value) == core.MSG_FORMAT == "설치 목록 형식이 올바르지 않아요. 허브를 새로 받아 주세요."


@pytest.mark.parametrize("raw", [b"not json", b"[]"])
def test_parse_manifest_rejects_non_object(raw):
    with pytest.raises(HubError, match="형식이 올바르지 않아요"):
        parse_manifest(raw)


def test_parse_manifest_newer_schema():
    m = good_manifest()
    m["schema"] = 2
    with pytest.raises(HubError) as e:
        parse_manifest(m)
    assert "업데이트" in str(e.value)
    assert str(e.value) == "이 허브로는 새 목록을 읽을 수 없어요. 허브를 업데이트해 주세요."


# 2. Source

def test_source_urls():
    s = Source()
    assert s.https_only
    assert s.manifest_url() == REPO_URL + "/releases/latest/download/manifest.json"
    assert s.asset_url("1.1.0", "a.zip") == REPO_URL + "/releases/download/v1.1.0/a.zip"
    assert REPO_URL == "https://github.com/Imtylerrrrrr/splitwave"
    b = Source("http://127.0.0.1:8000/rel/")
    assert not b.https_only
    assert b.manifest_url() == "http://127.0.0.1:8000/rel/manifest.json"
    assert b.asset_url("1.1.0", "a.zip") == "http://127.0.0.1:8000/rel/a.zip"


# 3, 4. 새 설치

def test_fresh_install(hub, srv):
    install_two(hub, srv)
    d = app_dir(hub)
    assert listing(d) == ["data.bin", "demo.exe", "lib/a.dll", "lib/b.dll"]
    assert (d / "lib/a.dll").read_bytes() == b"a-v1"
    assert (d / "data.bin").read_bytes() == b"data-v1"
    rec = hub.installed()["demo"]
    assert rec["name"] == "Demo" and rec["version"] == "1.0.0" and rec["exe"] == "demo.exe"
    assert sorted(rec["parts"]["app"]["files"]) == ["demo.exe", "lib/a.dll", "lib/b.dll"]
    assert rec["parts"]["data"] == {"content": sha(b"data-v1"), "files": ["data.bin"]}
    assert list((hub.root / "downloads").iterdir()) == []
    m = hub.fetch_manifest()
    assert hub.status(m.app("demo")) == core.Status(UP_TO_DATE, "1.0.0", 0)
    assert json.loads((hub.root / "state.json").read_text(encoding="utf-8"))["schema"] == 1


def test_status_not_installed(hub, srv):
    parts = [srv.part("app", "app.zip", BASE_MEMBERS)]
    srv.publish(parts)
    m = hub.fetch_manifest()
    assert hub.status(m.app("demo")) == core.Status(NOT_INSTALLED, None, parts[0]["size"])


def test_plain_file_part_copied(hub, srv):
    srv.publish([srv.part("app", "demo.exe", b"MZ-binary")])
    hub.install(hub.fetch_manifest(), "demo")
    assert listing(app_dir(hub)) == ["demo.exe"]
    assert (app_dir(hub) / "demo.exe").read_bytes() == b"MZ-binary"


def test_progress_is_cumulative(hub, srv):
    parts = [srv.part("app", "app.zip", BASE_MEMBERS), srv.part("data", "data.bin", b"d" * 200_000)]
    srv.publish(parts)
    calls = []
    hub.install(hub.fetch_manifest(), "demo", lambda done, total, name: calls.append((done, total, name)))
    total = sum(p["size"] for p in parts)
    assert all(t == total for _, t, _ in calls)
    assert calls[-1] == (total, total, "data.bin")
    assert [c[0] for c in calls] == sorted(c[0] for c in calls)


# 5. 업데이트

def test_update_downloads_only_changed_part(hub, srv):
    install_two(hub, srv)
    new_members = {"demo.exe": b"exe-v2", "lib/a.dll": b"a-v2"}  # lib/b.dll 빠짐
    parts = [srv.part("app", "app.zip", new_members), srv.part("data", "data.bin", b"data-v1")]
    srv.publish(parts, version="1.1.0")
    m = hub.fetch_manifest()
    assert hub.status(m.app("demo")) == core.Status(UPDATE_AVAILABLE, "1.0.0", parts[0]["size"])
    srv.requests.clear()
    data_mtime = (app_dir(hub) / "data.bin").stat().st_mtime_ns
    hub.install(m, "demo")
    assert srv.requests == ["/app.zip"]
    assert listing(app_dir(hub)) == ["data.bin", "demo.exe", "lib/a.dll"]
    assert (app_dir(hub) / "demo.exe").read_bytes() == b"exe-v2"
    assert (app_dir(hub) / "data.bin").stat().st_mtime_ns == data_mtime
    assert hub.installed()["demo"]["version"] == "1.1.0"
    assert hub.status(m.app("demo")).state == UP_TO_DATE


def test_install_noop_when_up_to_date(hub, srv):
    install_two(hub, srv)
    m = hub.fetch_manifest()
    srv.requests.clear()
    hub.install(m, "demo")
    assert srv.requests == []


# 6. 사라진 part

def test_removed_part_is_deleted(hub, srv):
    parts = install_two(hub, srv)
    srv.publish([parts[0]], version="1.1.0")
    m = hub.fetch_manifest()
    assert hub.status(m.app("demo")) == core.Status(UPDATE_AVAILABLE, "1.0.0", 0)
    hub.install(m, "demo")
    assert srv.requests == ["/manifest.json"]
    assert listing(app_dir(hub)) == ["demo.exe", "lib/a.dll", "lib/b.dll"]
    assert set(hub.installed()["demo"]["parts"]) == {"app"}
    assert hub.status(m.app("demo")).state == UP_TO_DATE


# 7. 지워진 파일 복구

def test_missing_file_is_repaired(hub, srv):
    install_two(hub, srv)
    (app_dir(hub) / "lib/b.dll").unlink()
    m = hub.fetch_manifest()
    st = hub.status(m.app("demo"))
    assert st.state == UPDATE_AVAILABLE
    assert st.download_size == (srv.dir / "app.zip").stat().st_size
    srv.requests.clear()
    hub.install(m, "demo")
    assert srv.requests == ["/app.zip"]
    assert (app_dir(hub) / "lib/b.dll").read_bytes() == b"b-v1"
    assert hub.status(m.app("demo")).state == UP_TO_DATE


# 8. 해시, 크기 불일치

@pytest.mark.parametrize("field", ["sha256", "size"])
def test_corrupt_download(hub, srv, field):
    p = srv.part("app", "app.zip", BASE_MEMBERS)
    p[field] = "f" * 64 if field == "sha256" else p["size"] + 1
    srv.publish([p])
    with pytest.raises(HubError) as e:
        hub.install(hub.fetch_manifest(), "demo")
    assert str(e.value) == "받은 파일이 손상됐어요. 다시 시도해 주세요."
    assert listing(app_dir(hub)) == []
    assert list((hub.root / "downloads").glob("*.part")) == []
    assert hub.installed() == {}


def test_corrupt_second_part_leaves_nothing(hub, srv):
    good = srv.part("app", "app.zip", BASE_MEMBERS)
    bad = srv.part("data", "data.bin", b"data")
    bad["sha256"] = "f" * 64
    srv.publish([good, bad])
    with pytest.raises(HubError, match="손상"):
        hub.install(hub.fetch_manifest(), "demo")
    assert listing(app_dir(hub)) == []
    assert list((hub.root / "downloads").glob("*.part")) == []


# 9. zip 경로 위반

def evil_zip(bad_name, symlink=False):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ok.txt", b"ok")
        info = zipfile.ZipInfo(bad_name)
        if symlink:
            info.external_attr = (0o120777 << 16)
            info.create_system = 3
        zf.writestr(info, b"target")
    return buf.getvalue()


@pytest.mark.parametrize("name,symlink", [("../x", False), ("/abs", False), ("..\\x", False),
                                          ("C:/x", False), ("link", True)])
def test_zip_path_violation(hub, srv, tmp_path, name, symlink):
    data = evil_zip(name, symlink)
    # 사전 확인: 만든 zip 에 위반 이름이 실제로 들어갔는지.
    # Windows 의 zipfile 은 ZipInfo 를 만들 때 \\ 를 / 로 바꿔 저장하므로 (그 경우 "../x" 와 같은 사례가 된다) 구분자만 맞춰 비교한다.
    stored = zipfile.ZipFile(io.BytesIO(data)).namelist()[1]
    assert stored.replace("\\", "/") == name.replace("\\", "/")
    if os.sep == "/":
        assert stored == name
    (srv.dir / "app.zip").write_bytes(data)
    srv.publish([{"id": "app", "file": "app.zip", "size": len(data), "unpacked": 8,
                  "sha256": sha(data), "content": H}])
    with pytest.raises(HubError) as e:
        hub.install(hub.fetch_manifest(), "demo")
    assert str(e.value) == "설치 파일에 허용되지 않는 경로가 있어요."
    assert listing(app_dir(hub)) == []
    assert not (tmp_path / "root" / "apps" / "x").exists()
    assert not (tmp_path / "root" / "x").exists()
    assert not (tmp_path / "x").exists()
    assert list((hub.root / "downloads").iterdir()) == []


# 10. 삭제

def test_remove_deletes_app_folder(hub, srv):
    install_two(hub, srv)
    hub.remove("demo")
    assert not app_dir(hub).exists()
    assert hub.installed() == {}


def test_remove_keeps_user_files(hub, srv):
    install_two(hub, srv)
    (app_dir(hub) / "lib" / "mine.txt").write_text("user")
    hub.remove("demo")
    assert listing(app_dir(hub)) == ["lib/mine.txt"]
    assert hub.installed() == {}


# 11. 미설치 앱

def test_not_installed_errors(hub):
    for call in (lambda: hub.remove("demo"), lambda: hub.launch("demo")):
        with pytest.raises(HubError) as e:
            call()
        assert str(e.value) == "설치되지 않은 앱이에요."


def test_unknown_app_install(hub, srv):
    srv.publish([srv.part("app", "demo.exe", b"x")])
    with pytest.raises(HubError, match="^목록에 없는 앱이에요.$"):
        hub.install(hub.fetch_manifest(), "other")


# 12. 공간 부족

def test_not_enough_space(hub, srv, monkeypatch):
    parts = [srv.part("app", "app.zip", BASE_MEMBERS), srv.part("data", "data.bin", b"d" * 3_000_000)]
    srv.publish(parts)
    m = hub.fetch_manifest()
    monkeypatch.setattr(shutil, "disk_usage", lambda p: types.SimpleNamespace(total=1, used=1, free=1000))
    need = sum(p["size"] + p["unpacked"] for p in parts) + 50 * 1024 * 1024
    n = -(-need // (1024 * 1024))
    with pytest.raises(HubError) as e:
        hub.install(m, "demo")
    assert str(e.value) == f"디스크 공간이 부족해요. 약 {n} MB가 필요해요."
    assert n == 56
    assert srv.requests == ["/manifest.json"]
    assert listing(app_dir(hub)) == []


# 13. 네트워크

def test_fetch_manifest_server_down(tmp_path):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    hub = Hub(tmp_path / "root", Source(f"http://127.0.0.1:{port}"))
    with pytest.raises(HubError) as e:
        hub.fetch_manifest()
    assert str(e.value) == "인터넷에 연결하지 못했어요. 연결을 확인하고 다시 시도해 주세요."


def test_fetch_manifest_404(hub):
    with pytest.raises(HubError, match="인터넷에 연결하지 못했어요"):
        hub.fetch_manifest()


# 14. 깨진 state.json

def test_broken_state_is_empty(hub, srv):
    hub.root.mkdir(parents=True)
    (hub.root / "state.json").write_text("{broken", encoding="utf-8")
    assert hub.installed() == {}
    srv.publish([srv.part("app", "demo.exe", b"x")])
    m = hub.fetch_manifest()
    assert hub.status(m.app("demo")).state == NOT_INSTALLED
    hub.install(m, "demo")
    assert hub.status(m.app("demo")).state == UP_TO_DATE


# 15. child_env

def test_child_env(monkeypatch):
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "x")
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    monkeypatch.setenv("_MEIPASS2", "y")
    monkeypatch.setenv("KEEP_ME", "z")
    env = child_env()
    assert not [k for k in env if k.startswith("_PYI_")]
    assert "_MEIPASS2" not in env
    assert env["KEEP_ME"] == "z"
    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "_MEIPASS2" in os.environ


# 16. launch

def test_launch(hub, srv, monkeypatch):
    srv.publish([srv.part("app", "app.zip", {"bin/demo.exe": b"exe"})], exe="bin/demo.exe")
    hub.install(hub.fetch_manifest(), "demo")
    monkeypatch.setenv("_PYI_X", "1")
    seen = {}

    def fake_popen(cmd, cwd=None, env=None):
        seen.update(cmd=cmd, cwd=cwd, env=env)
        return "proc"

    monkeypatch.setattr(core.subprocess, "Popen", fake_popen)
    assert hub.launch("demo", ["--selftest", "a"]) == "proc"
    exe = app_dir(hub) / "bin" / "demo.exe"
    assert seen["cmd"] == [str(exe), "--selftest", "a"]
    assert seen["cwd"] == str(exe.parent)
    assert seen["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert "_PYI_X" not in seen["env"]


@pytest.mark.skipif(os.name == "nt", reason="Windows 에서는 실제 잠금으로 판정")
def test_is_running_false_off_windows(hub, srv):
    install_two(hub, srv)
    assert hub.is_running("demo") is False
    assert hub.is_running("other") is False


# 17. hub_update_available

def test_hub_update_available(hub, tmp_path, monkeypatch):
    exe = tmp_path / "splitwave-hub.exe"
    exe.write_bytes(b"hub-v1")
    m = parse_manifest({"schema": 1, "version": "1.0.0",
                        "self_update": {"file": "splitwave-hub.exe", "size": 6, "sha256": sha(b"hub-v1")}, "apps": []})
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert hub.hub_update_available(m) is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert hub.hub_update_available(m) is False
    exe.write_bytes(b"hub-v0")
    assert hub.hub_update_available(m) is True


def test_hub_update_is_decided_by_version_when_manifest_has_one(hub, tmp_path, monkeypatch):
    """허브는 릴리스마다 다시 빌드되어 바이트가 달라진다. 매니페스트에 hub.version 이 있으면
    해시가 달라도 버전이 같을 때는 업데이트가 아니다."""
    import hub.core as core
    exe = tmp_path / "splitwave-hub.exe"
    exe.write_bytes(b"same code, rebuilt, different bytes")
    monkeypatch.setattr(sys, "executable", str(exe))

    def manifest(version):
        return parse_manifest({"schema": 1, "version": "1.3.0", "apps": [],
                               "self_update": {"file": "splitwave-hub.exe", "size": 6,
                                       "sha256": sha(b"hub-v1"), "version": version}})

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert manifest(core.HUB_VERSION).hub.version == core.HUB_VERSION
    assert hub.hub_update_available(manifest(core.HUB_VERSION)) is False
    assert hub.hub_update_available(manifest("9.9.9")) is True
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert hub.hub_update_available(manifest("9.9.9")) is False      # 소스로 실행 중이면 항상 없음


def test_manifest_hub_version_is_optional_but_validated():
    base = {"schema": 1, "version": "1.0.0", "apps": []}
    hubf = {"file": "splitwave-hub.exe", "size": 6, "sha256": "a" * 64}
    assert parse_manifest({**base, "self_update": hubf}).hub.version is None
    with pytest.raises(HubError):
        parse_manifest({**base, "self_update": {**hubf, "version": "not a version"}})
    with pytest.raises(HubError):
        parse_manifest({**base, "self_update": {**hubf, "version": 12}})


# 18. self_update

def test_self_update(hub, srv, tmp_path, monkeypatch):
    new = b"new hub binary"
    (srv.dir / "splitwave-hub.exe").write_bytes(new)
    srv.publish([srv.part("app", "demo.exe", b"x")], version="1.2.0",
                hub={"file": "splitwave-hub.exe", "size": len(new), "sha256": sha(new)})
    m = hub.fetch_manifest()
    exe = tmp_path / "bin" / "splitwave-hub.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"old hub")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert hub.hub_update_available(m)
    assert hub.self_update(m) == exe
    assert exe.read_bytes() == new
    assert (exe.parent / "splitwave-hub.exe.old").read_bytes() == b"old hub"
    assert not (exe.parent / "splitwave-hub.exe.new").exists()
    assert not hub.hub_update_available(m)
    hub.cleanup_old_self()
    assert not (exe.parent / "splitwave-hub.exe.old").exists()
    assert sorted(p.name for p in exe.parent.iterdir()) == ["splitwave-hub.exe"]


def test_self_update_corrupt_keeps_old(hub, srv, tmp_path, monkeypatch):
    (srv.dir / "splitwave-hub.exe").write_bytes(b"new")
    srv.publish([srv.part("app", "demo.exe", b"x")],
                hub={"file": "splitwave-hub.exe", "size": 3, "sha256": "f" * 64})
    exe = tmp_path / "splitwave-hub.exe"
    exe.write_bytes(b"old")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    with pytest.raises(HubError, match="손상"):
        hub.self_update(hub.fetch_manifest())
    assert exe.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("splitwave-hub")) == ["splitwave-hub.exe"]


# 19. check_final_url

def test_check_final_url():
    with pytest.raises(HubError, match="인터넷에 연결하지 못했어요"):
        check_final_url("http://github.com/x", True)
    check_final_url("https://objects.githubusercontent.com/x", True)
    check_final_url("http://127.0.0.1:8000/x", False)


def test_default_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert core.default_root() == tmp_path / "Splitwave"
    monkeypatch.delenv("LOCALAPPDATA")
    assert core.default_root() == core.Path.home() / ".local" / "share" / "Splitwave"


def test_log_appends_line(hub):
    hub.log("hello")
    hub.log("world")
    lines = (hub.root / "hub.log").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and lines[0].endswith(" hello")


def test_manifest_reads_self_update_and_ignores_the_old_hub_key():
    """v1.1.0, v1.2.0 허브는 매니페스트의 hub 항목이 자기와 다르면 화면이 비었다.
    그래서 새 매니페스트는 hub 를 쓰지 않고, 새 허브는 self_update 만 읽는다."""
    base = {"schema": 1, "version": "1.2.1", "apps": []}
    entry = {"file": "splitwave-hub.exe", "size": 10, "sha256": H, "version": "1.2.1"}
    assert parse_manifest({**base, "self_update": entry}).hub.version == "1.2.1"
    assert parse_manifest({**base, "hub": entry}).hub is None
