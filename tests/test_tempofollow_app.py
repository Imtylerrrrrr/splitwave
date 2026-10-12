"""Tempo Follow 화면. 엔진은 시작하지 않는다 (마이크·스피커 금지)."""
import os

import pytest

pytest.importorskip("customtkinter")
pytest.importorskip("sounddevice")

import library  # noqa: E402
import tempofollow.app as tfapp  # noqa: E402


def _make_app(monkeypatch, tmp_path):
    """설정 파일과 보관함을 tmp_path 아래로 격리해 앱을 만든다."""
    import tkinter

    monkeypatch.setattr(library, "config_path", lambda: tmp_path / "config.json")
    save_dir = tmp_path / "save"
    save_dir.mkdir(exist_ok=True)
    settings = library.load_settings()
    settings["last_dir"] = str(save_dir)
    library.save_settings(settings)
    try:
        app = tfapp.App()
    except tkinter.TclError as e:
        pytest.skip(f"GUI를 만들 수 없음: {e}")
    app.update()
    return app


def _run_immediately(**kw):
    kw["target"](*kw.get("args", ()))

    class _Done:
        def start(self):
            pass

    return _Done()


def test_status_text_stages():
    base = dict(playing=True, locked=False, beats_ok=None, phase_ms=None, bleed_delay_ms=None)
    assert tfapp.status_text(dict(base, playing=False), True) == "드럼을 치면 시작합니다"
    assert tfapp.status_text(base, True) == "템포 찾는 중"
    assert tfapp.status_text(dict(base, locked=True), False) == "따라가는 중"
    assert tfapp.status_text(dict(base, locked=True, beats_ok=True, phase_ms=31.6), False) \
        == "따라가는 중 · 박자 오차 +32 ms"
    assert tfapp.status_text(dict(base, locked=True, beats_ok=True, phase_ms=-8.0,
                                  bleed_delay_ms=95.2), False) \
        == "따라가는 중 · 박자 오차 -8 ms · 스피커 소리 상쇄 중 (지연 95 ms)"
    assert tfapp.status_text(dict(base, beats_ok=False), False) \
        == "템포 찾는 중 · 곡에서 박을 못 찾아 박자 맞춤은 꺼짐"
    # 템포를 잡기 전에는 박자 오차를 보이지 않는다
    assert tfapp.status_text(dict(base, beats_ok=True, phase_ms=10.0), False) == "템포 찾는 중"


def test_song_file_for_stem_bundle(tmp_path):
    lib = tmp_path / "lib"
    (lib / "song_stems").mkdir(parents=True)
    (lib / "other_stems").mkdir()
    for p in ("song.mp3", "song_stems/건반.wav", "other_stems/드럼.wav"):
        (lib / p).write_bytes(b"x")
    tracks = library.list_tracks(str(lib))
    by_label = {t.label: t.path for t in tracks}
    assert tfapp.song_file_for(tracks, by_label["song / 건반"]) == os.path.abspath(str(lib / "song.mp3"))
    assert tfapp.song_file_for(tracks, by_label["song"]) is None          # 곡 자체
    assert tfapp.song_file_for(tracks, by_label["other / 드럼"]) is None   # 곡 파일 없음


def test_window_fits_and_is_wider(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        assert app.winfo_width() == 560
        bottom = app.status_label.winfo_y() + app.status_label.winfo_height()
        assert bottom <= app.winfo_height(), (bottom, app.winfo_height())
        assert [l.cget("text") for l in app.num_labels] == ["-"] * 4
        assert app.phase_check.get() == 1
        right = app.winfo_rootx() + app.winfo_width()
        for w in (app.library_menu, app.in_menu, app.out_menu, app.phase_check):
            assert w.winfo_rootx() + w.winfo_width() <= right, w
    finally:
        app.destroy()


def test_settings_roundtrip(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        app.hit_slider.set(-30)
        app.range_entry.delete(0, "end")
        app.range_entry.insert(0, "20")
        app.hit_check.deselect()
        app.phase_check.deselect()
        app._save_settings()
    finally:
        app.destroy()
    saved = library.load_settings()[tfapp.SETTINGS_KEY]
    assert saved["hit_db"] == -30 and saved["range_pct"] == 20
    assert saved["wait_for_hit"] is False and saved["follow_phase"] is False
    assert saved["input"] and saved["output"]
    assert library.load_settings()["last_dir"] == str(tmp_path / "save")    # 다른 항목은 그대로

    app = _make_app(monkeypatch, tmp_path)
    try:
        assert app.hit_slider.get() == -30
        assert app.hit_value.cget("text") == "-30 dB"
        assert app.range_entry.get() == "20"
        assert app.hit_check.get() == 0 and app.phase_check.get() == 0
        assert app.in_menu.get() == saved["input"] and app.out_menu.get() == saved["output"]
    finally:
        app.destroy()


def test_settings_ignore_unknown_device(monkeypatch, tmp_path):
    monkeypatch.setattr(library, "config_path", lambda: tmp_path / "config.json")
    library.save_settings({"last_dir": str(tmp_path), tfapp.SETTINGS_KEY: {
        "input": "없는 마이크", "output": "없는 출력", "hit_db": "bad"}})
    app = _make_app(monkeypatch, tmp_path)
    try:
        assert app.in_menu.get() != "없는 마이크"
        assert app.out_menu.get() != "없는 출력"
        assert app.hit_slider.get() == -20
    finally:
        app.destroy()


def test_library_choice_loads_stem_with_song_as_beat_source(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        lib = library.library_dir(str(tmp_path / "save"))
        os.makedirs(os.path.join(lib, "song_stems"))
        for p in ("song.mp3", "song_stems/건반.wav"):
            with open(os.path.join(lib, p), "wb") as f:
                f.write(b"x")
        loads = []
        monkeypatch.setattr(app, "_load_file", lambda path, beat_path=None: loads.append((path, beat_path)))
        app.on_refresh_library()
        app.on_choose_library("song / 건반")
        app.on_choose_library("song")
        assert loads == [
            (os.path.abspath(os.path.join(lib, "song_stems", "건반.wav")),
             os.path.abspath(os.path.join(lib, "song.mp3"))),
            (os.path.abspath(os.path.join(lib, "song.mp3")), None),
        ]
    finally:
        app.destroy()


def test_load_fills_estimated_bpm(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    try:
        calls = []

        def fake_load(path, beat_path=None):
            calls.append((path, beat_path))
            app.engine.duration_s = 83.0
            app.engine.beat_source = "source"

        monkeypatch.setattr(app.engine, "load", fake_load)
        monkeypatch.setattr(tfapp, "estimate_bpm", lambda mono, sr: 123.44)
        monkeypatch.setattr(tfapp.threading, "Thread", _run_immediately)
        app.bpm_entry.insert(0, "99")
        app._load_file("/x/a.mp3", "/x/song.mp3")
        app.update()
        assert calls == [("/x/a.mp3", "/x/song.mp3")]
        assert app.bpm_entry.get() == "123.4"
        assert app.status_label.cget("text") == "길이 1:23 · 추정 BPM 123.4 (틀리면 고치세요)"
    finally:
        app.destroy()
