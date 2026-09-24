import pytest

pytest.importorskip("demucs.api")


def test_selftest_full_loads_model(capsys):
    import main
    assert main.selftest() == 0
    assert "full build ok" in capsys.readouterr().out
