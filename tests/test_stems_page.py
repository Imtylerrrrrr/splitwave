import pytest

pytest.importorskip("demucs.api")

import stems_page  # noqa: E402
from separator import DEFAULT_STEMS  # noqa: E402


def _page():
    import main
    try:
        app = main.App()
    except Exception as e:
        pytest.skip(f"GUI를 만들 수 없음: {e}")
    app.update()
    assert isinstance(app.stems_page, stems_page.StemsPage)
    return app, app.stems_page


def test_default_stems_checked():
    app, page = _page()
    try:
        assert page.selected_stems() == DEFAULT_STEMS
    finally:
        app.destroy()


def test_resolve_input_prefers_file(tmp_path):
    app, page = _page()
    try:
        assert page.resolve_input() is None
        page.url_entry.insert(0, "https://youtu.be/abc")
        assert page.resolve_input() == ("url", "https://youtu.be/abc")
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        page.file_path = str(f)
        assert page.resolve_input() == ("file", str(f))
    finally:
        app.destroy()


def test_start_requires_stem(monkeypatch, tmp_path):
    app, page = _page()
    try:
        warned = []
        monkeypatch.setattr("stems_page.messagebox.showwarning", lambda *a: warned.append(a))
        started = []
        monkeypatch.setattr("stems_page.threading.Thread",
                            lambda **kw: started.append(kw) or _FakeThread())
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        page.file_path = str(f)
        for var in page.stem_vars.values():
            var.set(False)
        page.on_start_click()
        assert warned and started == [] and app.busy is False
    finally:
        app.destroy()


def test_start_blocked_when_busy(monkeypatch, tmp_path):
    app, page = _page()
    try:
        shown = []
        monkeypatch.setattr("stems_page.messagebox.showinfo", lambda *a: shown.append(a))
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        page.file_path = str(f)
        app.busy = True
        page.on_start_click()
        assert shown
    finally:
        app.destroy()


def test_folder_label_follows_app(monkeypatch, tmp_path):
    app, page = _page()
    try:
        monkeypatch.setattr("main.filedialog.askdirectory", lambda **kw: str(tmp_path))
        monkeypatch.setattr("main.save_settings", lambda s: None)
        app.choose_folder()
        assert page.folder_label.cget("text") == str(tmp_path)
    finally:
        app.destroy()


class _FakeThread:
    def start(self):
        pass
