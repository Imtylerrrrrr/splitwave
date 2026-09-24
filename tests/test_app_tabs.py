import builtins
import sys

import pytest

import stems_page


@pytest.fixture(autouse=True)
def lite_env(monkeypatch):
    """demucs 가 없는 라이트 환경 시뮬레이션."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "demucs" or name.startswith("demucs."):
            raise ImportError("no demucs (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for mod in [m for m in sys.modules if m == "demucs" or m.startswith("demucs.")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)


def _make_app():
    """디스플레이가 없으면 skip."""
    import main
    try:
        app = main.App()
    except Exception as e:  # tkinter.TclError 등
        pytest.skip(f"GUI를 만들 수 없음: {e}")
    app.update()
    return app


def test_app_has_two_tabs():
    app = _make_app()
    try:
        assert app.tabview.tab("다운로드") is not None
        assert app.tabview.tab("스템 분리") is not None
        assert app.busy is False
        assert not hasattr(app, "downloading")
    finally:
        app.destroy()


def test_folder_listeners_called(tmp_path, monkeypatch):
    app = _make_app()
    try:
        got = []
        app.folder_listeners.append(got.append)
        monkeypatch.setattr("main.filedialog.askdirectory", lambda **kw: str(tmp_path))
        monkeypatch.setattr("main.save_settings", lambda s: None)
        app.choose_folder()
        assert got == [str(tmp_path)]
        assert app.save_dir == str(tmp_path)
    finally:
        app.destroy()


def test_lite_placeholder_when_demucs_missing():
    """demucs import가 실패하면 스템 탭엔 안내 프레임만."""
    assert stems_page.stems_available() is False
    app = _make_app()
    try:
        assert isinstance(app.stems_page, stems_page.LitePlaceholder)
    finally:
        app.destroy()


def test_selftest_lite():
    import main
    assert main.selftest() == 0
