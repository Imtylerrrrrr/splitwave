import pytest

np = pytest.importorskip("numpy")

from tempofollow.tempo import TempoTracker, estimate_bpm, estimate_delay


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


def test_estimate_delay_finds_echo():
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 1, 44100)
    shifted = np.concatenate([np.zeros(3000), ref])[:44100]
    mic = 0.5 * shifted + rng.normal(0, 0.3, 44100)
    k, conf = estimate_delay(mic, ref, 22050)
    assert k == 3000
    assert conf > 6
    _, conf = estimate_delay(rng.normal(0, 1, 44100), ref, 22050)
    assert conf < 6


def test_deadband_ignores_playback_tempo():
    t = TempoTracker(48000, 110)
    t.playback_bpm = 100.0
    feed(t, clicks(100, 8, 48000))
    assert t.measurements == 0
    assert t.bpm == 110


def simulate(drum, seconds=45):
    """앱 출력이 120 ms 늦게 1.5배로 마이크에 새는 닫힌 루프."""
    sr = 44100
    base = 110.0
    delay = round(0.12 * sr)
    gain = 1.5
    step = round(0.25 * sr)
    tr = TempoTracker(sr, base)
    ratio = 1.0
    dl = np.zeros(delay)
    next_beat = 0
    rng = np.random.default_rng(1)
    n = int(0.005 * sr)
    burst = 0.8 * rng.uniform(-1, 1, n) * np.exp(-np.linspace(0, 5, n))
    for i in range(0, seconds * sr, step):
        ref = np.zeros(step)
        while next_beat < i + step:
            j = next_beat - i
            if j >= 0:
                ref[j:j + len(burst)] += burst[:step - j]
            next_beat += round(60 / (base * ratio) * sr)
        buf = np.concatenate([dl, ref])
        bleed, dl = buf[:step], buf[step:]
        mic = gain * bleed
        if drum is not None:
            mic = mic + drum[i:i + step]
        tr.process_ref(ref)
        tr.process(mic)
        target = np.clip(tr.bpm / base, 0.7, 1.4)
        ratio += float(np.clip(target - ratio, -0.02, 0.02))
        tr.playback_bpm = base * ratio
    return ratio


def test_closed_loop_bleed():
    # 드러머 없이 자기 소리만 들어도 혼자 빨라지지 않는다
    assert abs(simulate(None) - 1.0) < 0.005
    # 드러머가 100 BPM이면 블리드가 1.5배로 커도 드러머를 따른다
    assert abs(110 * simulate(clicks(100, 45, 44100)) - 100) < 2
