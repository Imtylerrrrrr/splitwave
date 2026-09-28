"""Splitwave Hub 명령줄 진입점과 selftest. 화면(hub.app)은 필요할 때만 import 한다."""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import sys
import tempfile
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from common import resource_path
from hub.core import Hub, HubError, Source


def _out(stream, msg: str) -> None:
    try:
        print(msg, file=stream)
    except Exception:
        pass


def _build_parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="splitwave-hub")
    top.add_argument("--root")
    top.add_argument("--base")
    top.add_argument("--selftest", action="store_true")
    sub = top.add_subparsers(dest="mode")

    cli_p = sub.add_parser("cli")
    cli_p.add_argument("--root", default=argparse.SUPPRESS)
    cli_p.add_argument("--base", default=argparse.SUPPRESS)
    cli_sub = cli_p.add_subparsers(dest="cmd", required=True)

    cli_sub.add_parser("status")
    install_p = cli_sub.add_parser("install")
    install_p.add_argument("app")
    remove_p = cli_sub.add_parser("remove")
    remove_p.add_argument("app")
    run_p = cli_sub.add_parser("run")
    run_p.add_argument("app")
    run_p.add_argument("--wait", action="store_true")
    run_p.add_argument("args", nargs="*")
    return top


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2

    if args.selftest:
        return selftest(args.root)

    if args.mode == "cli":
        return _run_cli(args)

    from hub.app import run
    run(Path(args.root) if args.root else None, args.base)
    return 0


def _run_cli(args: argparse.Namespace) -> int:
    hub = Hub(Path(args.root) if args.root else None, Source(args.base))
    try:
        if args.cmd == "status":
            _cmd_status(hub)
        elif args.cmd == "install":
            hub.install(hub.fetch_manifest(), args.app)
        elif args.cmd == "remove":
            hub.remove(args.app)
        elif args.cmd == "run":
            proc = hub.launch(args.app, args.args)
            if args.wait:
                return proc.wait()
        return 0
    except HubError as e:
        hub.log(str(e))
        _out(sys.stderr, str(e))
        return 1


def _cmd_status(hub: Hub) -> None:
    manifest = hub.fetch_manifest()
    for app in manifest.apps:
        status = hub.status(app)
        _out(sys.stdout,
             f"{app.id}\t{status.state}\t{status.installed_version or '-'}\t{status.download_size}")


# ---------- selftest (네트워크 주소는 127.0.0.1, 화면 없음) ----------

def selftest(root: str | None = None) -> int:
    log_hub = Hub(Path(root) if root else Path(tempfile.mkdtemp(prefix="splitwave-hub-selftest-")))
    try:
        _selftest_checks()
    except Exception as e:
        reason = str(e) or repr(e)
        _out(sys.stderr, reason)
        log_hub.log(f"selftest failed: {reason}")
        return 1
    _out(sys.stdout, "selftest: hub ok")
    return 0


def _selftest_checks() -> None:
    import ssl
    import customtkinter  # noqa: F401
    ssl.create_default_context()

    for name in ("assets/theme.json", "assets/icon.png", "assets/icon.ico"):
        with open(resource_path(name), "rb"):
            pass

    with tempfile.TemporaryDirectory(prefix="splitwave-hub-selftest-") as td:
        _selftest_install_cycle(Path(td))


def _selftest_install_cycle(td: Path) -> None:
    release_dir = td / "release"
    release_dir.mkdir()
    requests: list[str] = []

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            super().do_GET()

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=str(release_dir)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        hub = Hub(td / "install", Source(base))

        part_app = _write_part(release_dir, "app.zip", "app",
                                {"demo.exe": b"selftest-v1", "lib/a.dll": b"a-v1"})
        part_data = _write_part(release_dir, "data.bin", "data", b"data-v1")
        _publish(release_dir, [part_app, part_data], "1.0.0")
        hub.install(hub.fetch_manifest(), "demo")
        app_dir = td / "install" / "apps" / "demo"
        if (app_dir / "demo.exe").read_bytes() != b"selftest-v1" or not (app_dir / "data.bin").is_file():
            raise RuntimeError("install did not produce expected files")

        part_app2 = _write_part(release_dir, "app.zip", "app",
                                 {"demo.exe": b"selftest-v2", "lib/a.dll": b"a-v1"})
        _publish(release_dir, [part_app2, part_data], "1.1.0")
        manifest2 = hub.fetch_manifest()
        requests.clear()
        hub.install(manifest2, "demo")
        if requests != ["/app.zip"]:
            raise RuntimeError(f"update fetched unexpected parts: {requests}")
        if (app_dir / "demo.exe").read_bytes() != b"selftest-v2":
            raise RuntimeError("update did not replace changed part")

        hub.remove("demo")
        if app_dir.exists():
            raise RuntimeError("remove did not delete app folder")
    finally:
        httpd.shutdown()
        httpd.server_close()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_content(members: dict[str, bytes]) -> str:
    items = sorted(members.items())
    blob = "".join(f"{name}\0{_sha(data)}\n" for name, data in items)
    return _sha(blob.encode("utf-8"))


def _write_part(directory: Path, filename: str, part_id: str, payload) -> dict:
    if isinstance(payload, dict):
        with zipfile.ZipFile(directory / filename, "w") as zf:
            for name, data in payload.items():
                zf.writestr(name, data)
        raw = (directory / filename).read_bytes()
        content, unpacked = _zip_content(payload), sum(len(d) for d in payload.values())
    else:
        (directory / filename).write_bytes(payload)
        raw, content, unpacked = payload, _sha(payload), len(payload)
    return {"id": part_id, "file": filename, "size": len(raw), "unpacked": unpacked,
            "sha256": _sha(raw), "content": content}


def _publish(directory: Path, parts: list[dict], version: str) -> None:
    manifest = {"schema": 1, "version": version,
                "apps": [{"id": "demo", "name": "Demo", "description": "selftest",
                          "exe": "demo.exe", "parts": parts}]}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
