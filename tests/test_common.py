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


BOT_CHECK = ("ERROR: [youtube] RNgv9fU8v7g: Sign in to confirm you’re not a bot. "
             "Use --cookies-from-browser or --cookies for the authentication. "
             "See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  "
             "for how to manually pass cookies. Also see  "
             "https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies  "
             "for tips on effectively exporting YouTube cookies")


def test_translate_error_explains_youtube_bot_check():
    msg = common.translate_error(Exception(BOT_CHECK))
    assert "유튜브가 이 인터넷 연결을" in msg
    assert "다른 인터넷" in msg
    assert "cookies" not in msg          # 원문 영어 안내를 그대로 보여 주지 않는다


def test_translate_error_keeps_age_restriction_message():
    msg = common.translate_error(Exception("Sign in to confirm your age. This video may be inappropriate"))
    assert "연령 제한" in msg
