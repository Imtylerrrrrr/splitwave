import pytest

np = pytest.importorskip("numpy")

from tempofollow.stretch import WSOLA
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
    # 8초: 4초 창이 차고, 최근 2초 측정 중 6회가 일치해야 채택하므로 첫 채택이 5.5초쯤이다
    # (합의 규칙을 넣기 전에는 6초였다. 드럼 아닌 소리를 걸러내는 대가로 1.5초 늦어짐)
    t = TempoTracker(48000, base_bpm=110)
    feed(t, clicks(100, 8, 48000))
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
    k, conf = estimate_delay(mic, ref, 22050, 44100)
    assert abs(k - 3000) <= 2
    assert conf > 6
    _, conf = estimate_delay(rng.normal(0, 1, 44100), ref, 22050, 44100)
    assert conf < 6


def test_estimate_delay_ignores_edge_leakage():
    """저역 위주 신호: 사각 창 가장자리 누설이 고역 빈에서 lag 0 상관을 만든다.
    창·대역 제한이 없던 이전 구현은 여기서 0을 돌려줬다."""
    sr, delay = 44100, 5292
    rng = np.random.default_rng(11)
    x = rng.normal(0, 1, sr * 4)
    spec = np.fft.rfft(x)
    spec[np.fft.rfftfreq(len(x), 1 / sr) > 300] = 0      # 300 Hz 아래만 남김
    ref = np.fft.irfft(spec, len(x))
    ref = (0.3 * ref / np.abs(ref).max() + rng.normal(0, 1e-5, len(x))).astype(np.float32)
    mic = np.concatenate([np.zeros(delay, np.float32), ref])[:len(ref)]
    k, conf = estimate_delay(mic[sr:3 * sr], ref[sr:3 * sr], 22050, sr)
    assert abs(k - delay) <= 2
    assert conf > 6

def test_quiet_sounds_do_not_move_tempo():
    sr = 44100
    t = TempoTracker(sr, 110)
    feed(t, clicks(100, 8, sr))
    rng = np.random.default_rng(0)
    quiet = clicks(125, 10, sr) * (0.004 / 0.8) + rng.normal(0, 0.001, 10 * sr)
    feed(t, quiet.astype(np.float32))
    assert abs(t.bpm - 100) < 2


def test_deadband_ignores_playback_tempo():
    t = TempoTracker(48000, 110)
    t.playback_bpm = 100.0
    feed(t, clicks(100, 8, 48000))
    assert t.measurements == 0
    assert t.bpm == 110


def tones(bpm, seconds, sr):
    """3-3-2 리듬(마디당 8분음표 0, 3, 6번째)의 사인 음. 드럼이 아닌 음악 블리드."""
    y = np.zeros(int(seconds * sr), dtype=np.float32)
    n = int(0.25 * sr)
    na = int(0.02 * sr)
    env = np.concatenate([np.linspace(0, 1, na), np.exp(-np.linspace(0, 5, n - na))])
    tt = np.arange(n) / sr
    eighth = 60.0 / bpm / 2 * sr
    freqs = (220, 277, 330)
    k = 0
    for bar in range(int(len(y) / (8 * eighth)) + 1):
        for pos in (0, 3, 6):
            s = int((bar * 8 + pos) * eighth)
            if s + n > len(y):
                return y
            y[s:s + n] += 0.3 * env * np.sin(2 * np.pi * freqs[k % 3] * tt)
            k += 1
    return y


def simulate(drum, seconds=45, music=False):
    """앱 출력이 120 ms 늦게 마이크에 새는 닫힌 루프 (클릭 1.5배, 또는 늘린 음악 1.0배)."""
    sr = 44100
    base = 110.0
    delay = round(0.12 * sr)
    gain = 1.0 if music else 1.5
    step = round(0.25 * sr)
    tr = TempoTracker(sr, base)
    ratio = 1.0
    dl = np.zeros(delay)
    next_beat = 0
    rng = np.random.default_rng(1)
    n = int(0.005 * sr)
    burst = 0.8 * rng.uniform(-1, 1, n) * np.exp(-np.linspace(0, 5, n))
    if music:
        tone = tones(110, 60, sr)
        w = WSOLA(np.stack([tone, tone], axis=1))
        pend = np.zeros(0)
    for i in range(0, seconds * sr, step):
        if music:
            while len(pend) < step:    # 현재 재생 비율로 늘린 음
                pend = np.concatenate([pend, w.next_chunk(ratio).mean(axis=1)])
            ref, pend = pend[:step], pend[step:]
        else:
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
    return ratio, tr


def test_closed_loop_bleed():
    # 드러머 없이 자기 소리만 들어도 혼자 빨라지지 않는다
    assert abs(simulate(None)[0] - 1.0) < 0.005
    # 드러머가 100 BPM이면 블리드가 1.5배로 커도 드러머를 따른다
    assert abs(110 * simulate(clicks(100, 45, 44100))[0] - 100) < 2


def test_closed_loop_musical_bleed():
    # 늘려 튼 음악이 새어 들어도 드러머 없이는 측정 자체를 안 한다
    ratio, tr = simulate(None, music=True)
    assert abs(ratio - 1.0) < 0.005
    assert tr.measurements == 0
    # 드러머가 100 BPM이면 음악 블리드가 있어도 드러머를 따른다
    ratio, tr = simulate(clicks(100, 45, 44100), music=True)
    assert abs(110 * ratio - 100) < 2.5


def test_delay_found_when_ref_arrives_late():
    """출력 블록이 마이크 블록보다 늦게 도착해도(큐 순서) 지연을 찾아야 한다."""
    sr, delay, step = 44100, 5292, 1024
    rng = np.random.default_rng(7)
    ref = rng.normal(0, 0.1, sr * 10).astype(np.float32)
    mic = 0.5 * np.concatenate([np.zeros(delay, np.float32), ref])[:len(ref)]
    t = TempoTracker(sr, 110)
    for i in range(0, len(ref) - step, step):
        t.process(mic[i:i + step])
        if i >= 4 * step:                      # ref는 항상 4블록 늦게 들어온다
            j = i - 4 * step
            t.process_ref(ref[j:j + step])
    assert t.bleed_delay_s is not None
    assert abs(t.bleed_delay_s * sr - delay) <= 2
