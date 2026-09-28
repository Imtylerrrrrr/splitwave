import functools
import hashlib
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hub import cli
from hub.core import NOT_INSTALLED, UP_TO_DATE, UPDATE_AVAILABLE, Status


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Server:
    """127.0.0.1 임시 포트로 tmp_path/srv 를 제공하고 앱 하나("demo")짜리 매니페스트를 발행한다."""

    def __init__(self, directory):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(directory)))
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def publish(self, data: bytes = b"MZ-demo"):
        (self.dir / "demo.exe").write_bytes(data)
        part = {"id": "app", "file": "demo.exe", "size": len(data), "unpacked": len(data),
                "sha256": sha(data), "content": sha(data)}
        m = {"schema": 1, "version": "1.0.0",
             "apps": [{"id": "demo", "name": "Demo", "description": "d", "exe": "demo.exe", "parts": [part]}]}
        (self.dir / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
        return m, len(data)


@pytest.fixture
def srv(tmp_path):
    s = Server(tmp_path / "srv")
    yield s
    s.httpd.shutdown()
    s.httpd.server_close()


# 1. status 출력 형식

def test_cli_status_format(tmp_path, srv, capsys):
    _, size = srv.publish()
    root = tmp_path / "root"
    code = cli.main(["--root", str(root), "--base", srv.base, "cli", "status"])
    out, _ = capsys.readouterr()
    assert code == 0
    assert out == f"demo\t{NOT_INSTALLED}\t-\t{size}\n"


# 2. install 후 파일 존재, 종료 코드 0

def test_cli_install(tmp_path, srv, capsys):
    srv.publish(b"MZ-demo")
    root = tmp_path / "root"
    code = cli.main(["--root", str(root), "--base", srv.base, "cli", "install", "demo"])
    assert code == 0
    assert (root / "apps" / "demo" / "demo.exe").read_bytes() == b"MZ-demo"

    capsys.readouterr()
    code = cli.main(["--root", str(root), "--base", srv.base, "cli", "status"])
    out, _ = capsys.readouterr()
    assert code == 0
    assert out == f"demo\t{UP_TO_DATE}\t1.0.0\t0\n"


# 3. 없는 앱 install -> 1

def test_cli_install_unknown_app(tmp_path, srv, capsys):
    srv.publish()
    root = tmp_path / "root"
    code = cli.main(["--root", str(root), "--base", srv.base, "cli", "install", "nope"])
    err = capsys.readouterr().err
    assert code == 1
    assert err.strip() == "목록에 없는 앱이에요."
    assert (root / "hub.log").read_text(encoding="utf-8").strip().endswith("목록에 없는 앱이에요.")


# 4. remove

def test_cli_remove(tmp_path, srv, capsys):
    srv.publish()
    root = tmp_path / "root"
    cli.main(["--root", str(root), "--base", srv.base, "cli", "install", "demo"])
    capsys.readouterr()
    code = cli.main(["--root", str(root), "--base", srv.base, "cli", "remove", "demo"])
    assert code == 0
    assert not (root / "apps" / "demo").exists()


def test_cli_remove_not_installed(tmp_path, srv, capsys):
    root = tmp_path / "root"
    code = cli.main(["--root", str(root), "--base", srv.base, "cli", "remove", "demo"])
    err = capsys.readouterr().err
    assert code == 1
    assert err.strip() == "설치되지 않은 앱이에요."


# 5. run --wait -- a b 가 Popen 인자와 종료 코드를 전달

def test_cli_run_wait_passes_args(tmp_path, srv, monkeypatch):
    srv.publish()
    root = tmp_path / "root"
    cli.main(["--root", str(root), "--base", srv.base, "cli", "install", "demo"])

    seen = {}

    class FakeProc:
        def wait(self):
            return 7

    def fake_popen(cmd, cwd=None, env=None):
        seen.update(cmd=cmd, cwd=cwd)
        return FakeProc()

    import hub.core as core
    monkeypatch.setattr(core.subprocess, "Popen", fake_popen)
    code = cli.main(["--root", str(root), "--base", srv.base, "cli", "run", "demo", "--wait", "--", "a", "b"])
    assert code == 7
    assert seen["cmd"][-2:] == ["a", "b"]
    assert seen["cmd"][0].endswith("demo.exe")


# 6. 사용법 오류 -> 2

@pytest.mark.parametrize("argv", [["cli"], ["cli", "bogus"], ["cli", "install"]])
def test_usage_error(argv):
    assert cli.main(argv) == 2


# 7. selftest() == 0

def test_selftest_ok():
    assert cli.selftest() == 0


def test_selftest_writes_log_to_given_root(tmp_path):
    root = tmp_path / "selftest-root"
    assert cli.selftest(str(root)) == 0


# 8. status_text, fmt_mb, buttons_for 의 값이 spec 문구와 글자 그대로 같음

def test_app_pure_functions():
    from hub import app as hub_app

    assert hub_app.fmt_mb(27 * 1024 * 1024) == "27 MB"
    assert hub_app.fmt_mb(27447491) == "27 MB"

    assert hub_app.buttons_for(NOT_INSTALLED) == ["설치"]
    assert hub_app.buttons_for(UP_TO_DATE) == ["실행", "삭제"]
    assert hub_app.buttons_for(UPDATE_AVAILABLE) == ["업데이트", "실행", "삭제"]

    assert (hub_app.status_text(Status(NOT_INSTALLED, None, 27 * 1024 * 1024), None, False)
            == "설치 안 됨 · 받을 크기 27 MB")
    assert (hub_app.status_text(Status(UP_TO_DATE, "1.1.0", 0), None, False)
            == "설치됨 v1.1.0 · 최신")
    assert (hub_app.status_text(Status(UPDATE_AVAILABLE, "1.1.0", 47 * 1024 * 1024), "1.2.0", False)
            == "업데이트 있음 v1.1.0 → v1.2.0 · 받을 크기 47 MB")
    assert (hub_app.status_text(Status(UP_TO_DATE, "1.1.0", 0), None, True)
            == "설치됨 v1.1.0 (업데이트 확인 실패)")


def test_cli_run_reports_launch_failure_in_one_line(tmp_path, srv, monkeypatch, capsys):
    """실행 자체가 실패하면(백신 차단 등) 스택 대신 한 줄 문구와 종료 코드 1."""
    srv.publish()
    root = tmp_path / "root"
    assert cli.main(["--root", str(root), "--base", srv.base, "cli", "install", "demo"]) == 0

    def boom(*a, **k):
        raise PermissionError(13, "Access is denied")

    import hub.core as core
    monkeypatch.setattr(core.subprocess, "Popen", boom)
    capsys.readouterr()
    assert cli.main(["--root", str(root), "--base", srv.base, "cli", "run", "demo"]) == 1
    err = capsys.readouterr().err
    assert "예상하지 못한 오류가 났어요." in err and "Traceback" not in err
    assert "unexpected error" in (root / "hub.log").read_text(encoding="utf-8")
