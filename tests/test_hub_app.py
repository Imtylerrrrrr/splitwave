"""허브 화면: 허브 새 버전 안내가 떠도 앱 카드가 그려져야 한다.
v1.1.0 과 v1.2.0 허브는 안내 줄을 넣다가 오류가 나서 화면이 빈 채로 남았다."""
import tkinter

import pytest

pytest.importorskip("customtkinter")

from hub import app as hub_app  # noqa: E402
from hub import core  # noqa: E402

H = "a" * 64
PART = {"id": "app", "file": "demo.exe", "size": 5, "unpacked": 5, "sha256": H, "content": H}
MANIFEST = {
    "schema": 1, "version": "9.9.9",
    "self_update": {"file": "splitwave-hub.exe", "size": 10, "sha256": H, "version": "9.9.9"},
    "apps": [{"id": "demo", "name": "Demo", "description": "d", "exe": "demo.exe", "parts": [PART]},
             {"id": "demo2", "name": "Demo 2", "description": "d", "exe": "demo.exe", "parts": [PART]}],
}


def _make_app(monkeypatch, tmp_path, update_available):
    monkeypatch.setattr(hub_app.App, "refresh", lambda self: None)   # 네트워크로 목록을 받지 않는다
    monkeypatch.setattr(core.Hub, "hub_update_available", lambda self, m: update_available)
    try:
        app = hub_app.App(tmp_path / "root", "http://127.0.0.1:9")
    except tkinter.TclError as e:   # 디스플레이 없음. 다른 예외는 실패로 드러나야 한다
        pytest.skip(f"GUI를 만들 수 없음: {e}")
    app.check_failed = False
    app.manifest = core.parse_manifest(MANIFEST)
    return app


def test_cards_render_when_hub_update_is_available(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, update_available=True)
    try:
        app._render()
        app.update()
        assert app.hub_update_frame.winfo_manager() == "pack"
        assert len(app.cards_frame.winfo_children()) == 2
        # 안내 줄은 다시 확인 버튼 아래, 카드 목록 위
        assert app.refresh_btn.winfo_y() < app.hub_update_frame.winfo_y()
        assert app.hub_update_frame.winfo_rooty() < app.cards_frame.winfo_rooty()
    finally:
        app.destroy()


def test_update_row_hidden_when_hub_is_current(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path, update_available=False)
    try:
        app._render()
        app.update()
        assert app.hub_update_frame.winfo_manager() == ""
        assert len(app.cards_frame.winfo_children()) == 2
    finally:
        app.destroy()
