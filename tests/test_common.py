import common


def test_parse_key():
    assert common.parse_key("0 (원본)") == 0
    assert common.parse_key("+2") == 2
    assert common.parse_key("-3") == -3


def test_pitch_filter_is_tempo_preserving():
    f = common.pitch_filter(12)  # 한 옥타브 위 → asetrate 96000, atempo 0.5
    assert "asetrate=96000" in f
    assert "atempo=0.500000" in f


def test_is_youtube_url():
    assert common.is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert common.is_youtube_url("youtu.be/abc")
    assert not common.is_youtube_url("https://example.com/x")


def test_collect_filepaths_skips_missing(tmp_path):
    real = tmp_path / "a.m4a"
    real.write_bytes(b"x")
    info = {"entries": [
        {"requested_downloads": [{"filepath": str(real)}]},
        {"requested_downloads": [{"filepath": str(tmp_path / "missing.m4a")}]},
        None,
    ]}
    assert common.collect_filepaths(info) == [str(real)]


def test_common_has_no_gui_imports():
    import re
    src = open(common.__file__, encoding="utf-8").read()
    assert re.search(r"^\s*(import|from)\s+(customtkinter|yt_dlp)\b", src, re.M) is None
