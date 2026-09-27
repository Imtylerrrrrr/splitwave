import pytest

np = pytest.importorskip("numpy")

from tempofollow.tempo import TempoTracker, estimate_bpm


def clicks(bpm, seconds, sr):
    rng = np.random.default_rng(0)
    y = np.zeros(int(seconds * sr), dtype=np.float32)
    n = int(0.005 * sr)
    burst = 0.8 * rng.uniform(-1, 1, n) * np.exp(-np.linspace(0, 5, n))
    period = 60.0 / bpm * sr
    t = 0.0
    while int(t) + n <= len(y):
        y[int(t):int(t) + n] += burst
        t += period
    return y


def feed(tracker, y, block=480):
    for i in range(0, len(y), block):
        tracker.process(y[i:i + block])


def converged_tracker():
    t = TempoTracker(48000, base_bpm=110)
    feed(t, clicks(100, 6, 48000))
    return t


def test_estimate_bpm_click_track():
    bpm = estimate_bpm(clicks(100, 20, 44100), 44100)
    assert abs(bpm - 100) < 1.0


def test_tracker_converges_and_follows():
    t = converged_tracker()
    assert abs(t.bpm - 100) < 2
    feed(t, clicks(120, 8, 48000))
    assert abs(t.bpm - 120) < 2.4


def test_tracker_holds_on_silence():
    t = converged_tracker()
    silence = np.zeros(48000 * 5, dtype=np.float32)
    # 멈춘 직후 4초 창에는 아직 타격이 남아 있어 측정이 이어진다 (값은 100 근처)
    feed(t, silence)
    assert abs(t.bpm - 100) < 2
    held, count = t.bpm, t.measurements
    feed(t, silence)
    assert t.bpm == held
    assert t.measurements == count


def test_tracker_ignores_noise():
    rng = np.random.default_rng(0)
    t = TempoTracker(48000, base_bpm=110)
    feed(t, rng.normal(0, 0.1, 48000 * 6).astype(np.float32))
    assert t.measurements == 0
    assert t.bpm == 110


def test_estimate_bpm_rejects_silence():
    with pytest.raises(ValueError):
        estimate_bpm(np.zeros(44100 * 5), 44100)
