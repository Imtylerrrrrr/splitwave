import pytest

np = pytest.importorskip("numpy")

from tempofollow.stretch import WSOLA
from tempofollow.tempo import (MIN_BEAT_STRENGTH, TempoTracker, estimate_bpm, estimate_delay,
                               phase_correction, phase_error, track_beats)


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
    # 재생 템포와 0.5 % 안인 측정은 자기 소리일 수 있어 버린다.
    # 부분 창(2초)에서도 치우침이 0.5 % 를 넘으면 안 된다 (보간을 사전 가중치 없이 하는 이유)
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


def ramp_clicks(b0, b1, seconds, sr):
    """클릭 간격이 선형으로 빨라지는 클릭 트랙. 각 클릭 시점의 bpm = b0 + (b1-b0)·t/총길이."""
    rng = np.random.default_rng(0)
    y = np.zeros(int(seconds * sr), dtype=np.float32)
    n = int(0.005 * sr)
    burst = 0.8 * rng.uniform(-1, 1, n) * np.exp(-np.linspace(0, 5, n))
    times = []
    t = 0.0
    while int(t * sr) + n <= len(y):
        s = int(t * sr)
        y[s:s + n] += burst
        times.append(s / sr)
        t += 60.0 / (b0 + (b1 - b0) * t / seconds)
    return y, np.array(times)


def test_partial_window_adopts_sooner():
    # 창 3초 중 2초(최소 3박)만 차도 재므로 4초 안에 첫 채택이 나온다
    t = TempoTracker(44100, 110)
    feed(t, clicks(100, 4, 44100))
    assert t.measurements >= 1
    feed(t, clicks(100, 2, 44100))
    assert abs(t.bpm - 100) < 1


def test_track_beats_click_track():
    beats, strength = track_beats(clicks(100, 20, 44100), 44100, 100)
    assert strength > 0.8
    late = beats[beats > 1.0]
    err = late - np.round(late / 0.6) * 0.6
    assert np.abs(err).max() < 0.015
    assert abs(np.median(np.diff(beats)) - 0.6) < 0.005


def test_track_beats_follow_drift():
    y, times = ramp_clicks(100, 106, 30, 44100)
    beats, _ = track_beats(y, 44100, 100)
    late = beats[beats > 1.0]
    nearest = times[np.abs(late[:, None] - times[None, :]).argmin(axis=1)]
    assert np.abs(late - nearest).max() < 0.02


def test_track_beats_rejects_noise():
    rng = np.random.default_rng(0)
    noise = rng.uniform(-0.1, 0.1, 60 * 44100).astype(np.float32)
    _, strength = track_beats(noise, 44100, 100)
    assert strength < MIN_BEAT_STRENGTH
    _, strength = track_beats(clicks(100, 20, 44100), 44100, 100)
    assert strength >= MIN_BEAT_STRENGTH


def test_live_beat_phase_matches_clicks():
    sr = 44100
    t = TempoTracker(sr, 100)
    feed(t, clicks(100, 8, sr))
    assert t.beat_end is not None
    assert t.beat_conf > 3
    # 클릭은 0.6 s 배수에 있다
    assert abs(((t.beat_end / sr + 0.3) % 0.6) - 0.3) < 0.025
    assert t.beat_at > sr * 6


def test_phase_error_wraps():
    assert phase_error(130, 100, 100) == 30
    assert phase_error(180, 100, 100) == -20
    assert phase_error(80, 100, 100) == -20
    assert phase_error(150, 100, 100) == 50
    assert phase_correction(0.1) == 0.04
    assert phase_correction(-0.05) == -0.02
    assert phase_correction(0.5) == 0.04


def simulate_phase(drum, drum_offset_s, seconds=45, correct=True):
    """늘린 음악이 120 ms 늦게 마이크에 새는 닫힌 루프에서 박 위치 맞춤.
    시간축은 엔진과 같다: 내보낸 샘플 수가 ref 축, 마이크 축 = ref + 블리드 지연.
    (err 기록 시각(초), err(초)) 목록과 마지막 ratio 를 돌려준다."""
    sr = 44100
    base = 110.0
    delay = round(0.12 * sr)
    step = round(0.25 * sr)
    hop = 1024
    tr = TempoTracker(sr, base)
    ratio = 1.0
    dl = np.zeros(delay)
    tone = tones(110, 60, sr)
    beats, _ = track_beats(tone, sr, 110)
    beats = beats * sr
    w = WSOLA(np.stack([tone, tone], axis=1))
    pend = np.zeros(0)
    written = 0           # WSOLA 가 만든 샘플 수 (엔진의 _written)
    drum = np.concatenate([np.zeros(round(drum_offset_s * sr), np.float32), drum])
    errs = []
    for i in range(0, seconds * sr, step):
        while len(pend) < step:    # 현재 재생 비율로 늘린 음
            chunk = w.next_chunk(ratio).mean(axis=1)
            pend = np.concatenate([pend, chunk])
            written += len(chunk)
        ref, pend = pend[:step], pend[step:]
        buf = np.concatenate([dl, ref])
        bleed, dl = buf[:step], buf[step:]
        mic = bleed + drum[i:i + step]
        tr.process_ref(ref)
        tr.process(mic)
        target = float(np.clip(tr.bpm / base, 0.7, 1.4))
        err = None
        if tr.beat_end is not None and tr.mic_total - tr.beat_at <= 2.0 * sr:
            in_pos = w.in_pos + hop * ratio                 # 다음 청크의 곡 위치
            k = int(np.searchsorted(beats, in_pos))
            if k < len(beats):
                ref_idx = written + (beats[k] - in_pos) / ratio
                d = tr._delay if tr._delay is not None else delay
                err = phase_error(ref_idx + d, tr.beat_end, 60.0 / tr.bpm * sr) / sr
        if err is not None:
            errs.append(((i + step) / sr, err))
            if correct:
                target *= 1 + phase_correction(err)
        ratio += float(np.clip(target - ratio, -0.03, 0.03))
        tr.playback_bpm = base * ratio
    return ratio, errs


def _late_mean_abs(errs, seconds, last=10):
    return float(np.mean([abs(e) for t, e in errs if t > seconds - last]))


def test_closed_loop_phase_alignment():
    drum = clicks(100, 60, 44100)
    ratio, errs = simulate_phase(drum, 0.25, 45, correct=True)
    assert _late_mean_abs(errs, 45) < 0.03
    assert abs(110 * ratio - 100) < 2.5
    # 보정이 없으면 빠르기는 맞아도 박이 어긋난 채로 남는다
    _, errs = simulate_phase(drum, 0.25, 45, correct=False)
    assert _late_mean_abs(errs, 45) > 0.08
