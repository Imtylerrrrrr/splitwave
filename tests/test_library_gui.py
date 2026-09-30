# -*- coding: utf-8 -*-
"""보관함(Splitwave 폴더) 연동 화면 테스트: main.py / stems_page.py.
디스플레이가 없으면 skip (기존 GUI 테스트 방식). 실제 사용자 설정 파일과
실제 다운로드 폴더는 절대 건드리지 않는다 (library.config_path 를 tmp_path 로,
저장 폴더도 tmp_path 아래 폴더로 미리 설정)."""

import os
import time

import pytest

pytest.importorskip("demucs.api")

import library  # noqa: E402
import stems_page  # noqa: E402


def _make_app(monkeypatch, tmp_path):
    """디스플레이가 없으면 skip. 실제 설정 파일 대신 tmp_path 의 파일을 쓰고,
    저장 폴더도 last_dir 로 미리 tmp_path 아래 폴더를 지정해 둔다
    (그래야 App() 생성 중에 실제 다운로드 폴더를 건드리지 않는다)."""
    monkeypatch.setattr(library, "config_path", lambda: tmp_path / "config.json")
    save_dir = tmp_path / "save"
    save_dir.mkdir()
    library.save_settings({"last_dir": str(save_dir)})

    import tkinter

    import main
    try:
        app = main.App()
    except tkinter.TclError as e:   # 디스플레이 없음. 다른 예외는 실패로 드러나야 한다
        pytest.skip(f"GUI를 만들 수 없음: {e}")
    app.update()
    return app


def _touch(path: str, mtime: float | None = None) -> None:
    with open(path, "wb"):
        pass
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class _RecordingThread:
    """threading.Thread 대체: 실제로 시작하지 않고 kwargs 만 기록한다."""

    def __init__(self, log, **kw):
        log.append(kw)

    def start(self):
        pass


def _run_immediately(**kw):
    """threading.Thread 대체: target 을 그 자리에서(동기적으로) 실행한다."""
    target = kw["target"]
    args = kw.get("args", ())
    target(*args)

    class _NoOpThread:
        def start(self):
            pass

    return _NoOpThread()


# ── 1. 보관함 파일 2개 → 드롭다운 = 안내 항목 + 곡 2개(최신순) ──

def test_dropdown_shows_songs_newest_first(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        lib = app.library_dir
        now = time.time()
        _touch(os.path.join(lib, "old song.mp3"), now - 100)
        _touch(os.path.join(lib, "new song.mp3"), now)

        app.stems_page.refresh_library_menu()

        assert app.stems_page.library_menu.cget("values") == [
            stems_page.LIBRARY_GUIDE_ITEM, "new song", "old song",
        ]
    finally:
        app.destroy()


# ── 2. 드롭다운에서 곡을 고르면 file_path/resolve_input 이 바뀐다 ──

def test_selecting_song_sets_file_path(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        lib = app.library_dir
        song_path = os.path.join(lib, "hello.mp3")
        _touch(song_path)

        page = app.stems_page
        page.refresh_library_menu()
        label = next(iter(page.song_options))
        page.on_library_select(label)

        assert page.file_path == page.song_options[label]
        assert os.path.abspath(page.file_path) == os.path.abspath(song_path)
        assert page.resolve_input() == ("file", page.file_path)
    finally:
        app.destroy()


# ── 3. 지우기 → 드롭다운이 안내 항목으로 돌아간다 ──

def test_clear_resets_dropdown_to_guide_item(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        lib = app.library_dir
        song_path = os.path.join(lib, "hello.mp3")
        _touch(song_path)

        page = app.stems_page
        page.refresh_library_menu()
        label = next(iter(page.song_options))
        page.on_library_select(label)
        page.library_menu.set(label)

        page.on_clear_file()

        assert page.file_path is None
        assert page.library_menu.get() == stems_page.LIBRARY_GUIDE_ITEM
    finally:
        app.destroy()


# ── 4. 빈 보관함 → "(받은 곡이 없어요)" ──

def test_empty_library_shows_empty_item(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        page = app.stems_page
        page.refresh_library_menu()
        assert page.library_menu.cget("values") == [stems_page.LIBRARY_EMPTY_ITEM]
        assert page.library_menu.get() == stems_page.LIBRARY_EMPTY_ITEM
    finally:
        app.destroy()


# ── 5. notify_library_changed() 뒤 새 파일이 드롭다운에 나타난다 ──

def test_notify_library_changed_refreshes_dropdown(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        page = app.stems_page
        assert page.library_menu.cget("values") == [stems_page.LIBRARY_EMPTY_ITEM]

        lib = app.library_dir
        _touch(os.path.join(lib, "brand new.mp3"))

        app.notify_library_changed()

        assert "brand new" in page.library_menu.cget("values")
    finally:
        app.destroy()


# ── 6. 이미 받은 링크 → 확인창, 아니오면 시작 안 함 / 예면 시작 ──

def test_duplicate_download_confirmation(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        url = "https://www.youtube.com/watch?v=abcdefghijk"
        app.url_entry.insert(0, url)

        existing = os.path.join(app.library_dir, "existing.mp3")
        monkeypatch.setattr(library, "find_downloaded", lambda lib, vid: [existing])

        started = []
        monkeypatch.setattr(
            "main.threading.Thread",
            lambda **kw: _RecordingThread(started, **kw))

        monkeypatch.setattr("main.messagebox.askyesno", lambda *a, **kw: False)
        app.on_download_click()
        assert started == []
        assert app.busy is False

        monkeypatch.setattr("main.messagebox.askyesno", lambda *a, **kw: True)
        app.on_download_click()
        assert len(started) == 1
        assert app.busy is True
    finally:
        app.destroy()


# ── 7. 다운로드 outtmpl / 스템 결과 폴더가 보관함 아래인지 ──

def test_download_and_stems_paths_under_library(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        lib = app.library_dir

        # main.py 다운로드: outtmpl 이 보관함 아래인지
        captured = {}

        class _FakeYDL:
            def __init__(self, opts):
                captured["opts"] = opts

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=True):
                return {"id": "abcdefghijk", "requested_downloads": []}

        monkeypatch.setattr("main.yt_dlp.YoutubeDL", _FakeYDL)
        monkeypatch.setattr("main.threading.Thread", _run_immediately)

        app.url_entry.insert(0, "https://www.youtube.com/watch?v=abcdefghijk")
        app.on_download_click()

        assert captured["opts"]["outtmpl"].startswith(lib + os.sep)

        app.busy = False  # 완료 후처리(after 콜백)는 굳이 돌리지 않고 직접 되돌린다

        # stems_page.py 분리: 결과 폴더가 보관함 아래인지
        page = app.stems_page
        song = os.path.join(lib, "mysong.mp3")
        _touch(song)
        page.file_path = song
        for var in page.stem_vars.values():
            var.set(True)
        app.ffmpeg_path = "fake-ffmpeg"

        sep_calls = {}

        def fake_separate(input_path, stems, out_dir, fmt, ffmpeg, semitones,
                          on_progress=None, minus=()):
            sep_calls["out_dir"] = out_dir
            return []

        monkeypatch.setattr("separator.separate", fake_separate)
        monkeypatch.setattr("stems_page.threading.Thread", _run_immediately)

        page.on_start_click()

        assert sep_calls["out_dir"].startswith(lib + os.sep)
    finally:
        app.destroy()


# ── 보관함 폴더를 만들 수 없어도 앱이 뜬다 ──

def test_app_starts_when_library_folder_cannot_be_created(monkeypatch, tmp_path):
    """저장 폴더가 쓰기 금지여도(보호된 폴더 등) 시작할 때 죽으면 안 된다.
    죽으면 저장 폴더를 바꿀 방법이 없어진다."""
    def deny(base):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(library, "ensure_library", deny)
    app = _make_app(monkeypatch, tmp_path)
    try:
        assert app.library_dir == library.library_dir(str(tmp_path / "save"))
        assert app.stems_page.library_menu.cget("values") == [stems_page.LIBRARY_EMPTY_ITEM]
    finally:
        app.destroy()


# ── 긴 곡 이름을 골라도 드롭다운이 넓어지지 않는다 ──

def test_long_song_name_does_not_widen_dropdown(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        page = app.stems_page
        before = page.library_menu.winfo_reqwidth()
        _touch(os.path.join(app.library_dir, "아주 긴 곡 제목 " * 8 + ".mp3"))
        page.refresh_library_menu()
        label = page.library_menu.cget("values")[1]
        page.library_menu.set(label)
        app.update()
        assert page.library_menu.winfo_reqwidth() == before
    finally:
        app.destroy()
