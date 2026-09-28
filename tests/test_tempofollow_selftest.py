import pytest

pytest.importorskip("numpy")
pytest.importorskip("sounddevice")

from common import find_ffmpeg


def test_selftest_ok(capsys):
    if not find_ffmpeg():
        pytest.skip("ffmpeg not found")

    from tempofollow.selftest import selftest

    assert selftest() == 0
    assert "tempofollow ok" in capsys.readouterr().out
