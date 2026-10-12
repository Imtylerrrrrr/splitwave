import os

import pytest

pytest.importorskip("demucs.api")

import library  # noqa: E402
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


def test_default_minus_unchecked():
    app, page = _page()
    try:
        assert page.selected_minus() == []
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
        assert all(not v.get() for v in page.minus_vars.values())
        page.on_start_click()
        assert warned and started == [] and app.busy is False
    finally:
        app.destroy()


def test_start_allows_minus_only(monkeypatch, tmp_path):
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
        page.minus_vars["guitar"].set(True)
        app.ffmpeg_path = "fake-ffmpeg"
        page.on_start_click()
        assert warned == []
        assert len(started) == 1
        assert started[0]["args"][1] == []
        assert started[0]["args"][2] == ["guitar"]
        assert app.busy is True
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
        # 스템 탭 폴더 글자는 저장 폴더가 아니라 보관함 경로를 보여준다 (library 설계 변경)
        assert page.folder_label.cget("text") == library.library_dir(str(tmp_path))
    finally:
        app.destroy()


def test_page_fits_in_window():
    """창 크기를 키우지 않고 줄을 넣었으니, 아래 버튼이 잘리지 않고
    두 체크박스 열이 탭 오른쪽 가장자리를 넘지 않아야 한다."""
    app, page = _page()
    try:
        app.tabview.set("스템 분리")
        app.update()
        assert page.open_btn.winfo_y() + page.open_btn.winfo_height() <= page.master.winfo_height()
        right_edge = page.winfo_rootx() + page.winfo_width()
        boxes = [cb for grid in (page.stem_grid, page.minus_grid) for cb in grid.winfo_children()]
        assert len(boxes) == 12
        for cb in boxes:
            assert cb.winfo_rootx() + cb.winfo_width() <= right_edge, cb.cget("text")
    finally:
        app.destroy()


class _FakeThread:
    def start(self):
        pass


def test_default_mix_unchecked():
    app, page = _page()
    try:
        assert page.mix_var.get() is False
    finally:
        app.destroy()


def test_start_passes_mix(monkeypatch, tmp_path):
    app, page = _page()
    try:
        started = []
        monkeypatch.setattr("stems_page.threading.Thread",
                            lambda **kw: started.append(kw) or _FakeThread())
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        page.file_path = str(f)
        page.mix_var.set(True)
        app.ffmpeg_path = "fake-ffmpeg"
        page.on_start_click()
        assert len(started) == 1
        assert started[0]["args"][5] is True
    finally:
        app.destroy()


def _run_immediately(**kw):
    """threading.Thread 대체: target 을 그 자리에서(동기적으로) 실행한다."""
    kw["target"](*kw.get("args", ()))
    return _FakeThread()


def _start_with_existing_folder(app, page, monkeypatch, tmp_path, answer, fill_folder=True):
    """결과 폴더(<곡>_stems)를 미리 만들어 두고 분리를 시작한다.
    묻는 창은 answer 를 돌려주는 가짜로 바꾸고, (물은 횟수, separate 가 받은 out_dir) 를 돌려준다."""
    asked = []
    monkeypatch.setattr("stems_page.messagebox.askyesnocancel",
                        lambda *a, **k: asked.append(a) or answer)
    monkeypatch.setattr("stems_page.messagebox.showinfo", lambda *a: None)
    sep_calls = []
    monkeypatch.setattr("separator.separate",
                        lambda input_path, stems, out_dir, *a, **k: sep_calls.append(out_dir) or [])
    monkeypatch.setattr("stems_page.threading.Thread", _run_immediately)
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    page.file_path = str(f)
    app.ffmpeg_path = "fake-ffmpeg"
    folder = os.path.join(app.library_dir, "a_stems")
    os.makedirs(folder, exist_ok=True)
    if fill_folder:
        with open(os.path.join(folder, "보컬.wav"), "wb"):
            pass
    page.on_start_click()
    app.update()
    return asked, sep_calls


def test_existing_result_folder_overwrite(monkeypatch, tmp_path):
    app, page = _page()
    try:
        asked, sep_calls = _start_with_existing_folder(app, page, monkeypatch, tmp_path, True)
        assert len(asked) == 1 and "a_stems" in asked[0][1]
        assert sep_calls == [os.path.join(app.library_dir, "a_stems")]
        assert app.busy is False
    finally:
        app.destroy()


def test_existing_result_folder_new_folder(monkeypatch, tmp_path):
    app, page = _page()
    try:
        asked, sep_calls = _start_with_existing_folder(app, page, monkeypatch, tmp_path, False)
        assert len(asked) == 1
        assert sep_calls == [os.path.join(app.library_dir, "a (2)_stems")]
    finally:
        app.destroy()


def test_existing_result_folder_cancel(monkeypatch, tmp_path):
    app, page = _page()
    try:
        asked, sep_calls = _start_with_existing_folder(app, page, monkeypatch, tmp_path, None)
        assert len(asked) == 1
        assert sep_calls == []
        assert app.busy is False
        assert page.start_btn.cget("text") == "분리 시작"
        assert page.start_btn.cget("state") == "normal"
        assert page.status_label.cget("text") == "취소됨"
    finally:
        app.destroy()


def test_empty_result_folder_does_not_ask(monkeypatch, tmp_path):
    app, page = _page()
    try:
        asked, sep_calls = _start_with_existing_folder(
            app, page, monkeypatch, tmp_path, None, fill_folder=False)
        assert asked == []
        assert sep_calls == [os.path.join(app.library_dir, "a_stems")]
    finally:
        app.destroy()
