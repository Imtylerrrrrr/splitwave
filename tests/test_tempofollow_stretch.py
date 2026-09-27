import pytest

np = pytest.importorskip("numpy")

from tempofollow.stretch import WSOLA

SR = 44100


def signal(seconds, sr=SR):
    rng = np.random.default_rng(0)
    t = np.arange(int(seconds * sr)) / sr
    x = 0.5 * np.sin(2 * np.pi * 440 * t) + rng.normal(0, 0.05, len(t))
    return np.stack([x, x], axis=1).astype(np.float32)


def run(w, ratio_fn):
    out, i = [], 0
    while True:
        chunk = w.next_chunk(ratio_fn(i))
        if chunk is None:
            return np.concatenate(out)
        out.append(chunk)
        i += 1


def test_identity_at_ratio_one():
    x = signal(3)
    w = WSOLA(x)
    y = run(w, lambda i: 1.0)
    n = min(len(y), len(x)) - w.hop
    assert np.max(np.abs(y[w.hop:n] - x[w.hop:n])) < 1e-4


def test_length_scales_with_ratio():
    x = signal(5)
    for ratio in (1.5, 0.7):
        w = WSOLA(x)
        y = run(w, lambda i: ratio)
        assert abs(len(y) - len(x) / ratio) < 2 * w.frame


def test_pitch_preserved():
    x = signal(4)
    for ratio in (1.25, 0.8):
        y = run(WSOLA(x), lambda i: ratio)
        assert not np.isnan(y).any()
        mono = y.mean(axis=1)
        freq = np.argmax(np.abs(np.fft.rfft(mono))) * SR / len(mono)
        assert abs(freq - 440) < 2


def test_ratio_can_change_midstream():
    y = run(WSOLA(signal(4)), lambda i: 0.8 if i % 50 < 25 else 1.3)
    assert len(y) > 0


def test_short_input_rejected():
    with pytest.raises(ValueError):
        WSOLA(np.zeros((1000, 2), dtype=np.float32))
