# -*- coding: utf-8 -*-
"""마이크 입력에서 템포(BPM) 추정. numpy만 쓴다 (테스트·CI용)."""

import math

import numpy as np


class OnsetStrength:
    """스펙트럼 플럭스 온셋 강도. hop 샘플마다 프레임 하나."""

    def __init__(self, sr: int, n_fft: int = 1024, hop: int = 256):
        self.n_fft = n_fft
        self.hop = hop
        self.hop_seconds = hop / sr
        self._buf = np.zeros(n_fft)
        self._pending = np.zeros(0)
        self._win = np.hanning(n_fft)
        self._prev = np.zeros(n_fft // 2 + 1)

    def process(self, mono: np.ndarray) -> np.ndarray:
        self._pending = np.concatenate([self._pending, np.asarray(mono, dtype=np.float64)])
        out = []
        while len(self._pending) >= self.hop:
            block, self._pending = self._pending[:self.hop], self._pending[self.hop:]
            self._buf = np.concatenate([self._buf[self.hop:], block])
            s = np.log1p(100 * np.abs(np.fft.rfft(self._buf * self._win)))
            out.append(np.maximum(s - self._prev, 0).sum())
            self._prev = s
        return np.array(out)


def estimate_delay(mic, ref, max_delay):
    """GCC-PHAT. mic[t] ≈ ref[t - k]인 k(샘플)와 신뢰도(피크 / RMS)."""
    n = 1 << (len(mic) + len(ref) - 1).bit_length()
    R = np.fft.rfft(mic, n) * np.conj(np.fft.rfft(ref, n))
    c = np.fft.irfft(R / (np.abs(R) + 1e-12), n)[: max_delay + 1]
    k = int(np.argmax(c))
    confidence = float(c[k] / (np.sqrt(np.mean(c ** 2)) + 1e-12))
    return k, confidence


def _acf_peak_bpm(o, sr, hop, bpm_lo, bpm_hi, prior_bpm, prior_sigma_oct):
    """온셋 강도 o의 자기상관 최대 lag → (bpm, confidence). 판단 불가면 None."""
    w_len = len(o)
    hann7 = np.hanning(7)
    o = np.convolve(o, hann7 / hann7.sum(), mode="same")
    x = o - o.mean()
    r = np.fft.irfft(np.abs(np.fft.rfft(x, 2 * w_len)) ** 2)[:w_len]
    if r[0] <= 0:
        return None
    r = r / r[0]
    r = r * (w_len / (w_len - np.arange(w_len)))

    lag_min = max(2, math.ceil(60 * sr / (bpm_hi * hop)))
    lag_max = min(math.floor(60 * sr / (bpm_lo * hop)), w_len // 2)
    if lag_min >= lag_max:
        return None
    lags = np.arange(lag_min, lag_max + 1)
    bpms = 60 * sr / (lags * hop)
    weight = np.exp(-0.5 * (np.log2(bpms / prior_bpm) / prior_sigma_oct) ** 2)
    score = r[lags] * weight
    i = int(np.argmax(score))
    confidence = float(r[lags[i]])

    delta = 0.0
    if 0 < i < len(score) - 1:
        a, b, c = score[i - 1], score[i], score[i + 1]
        denom = a - 2 * b + c
        delta = 0.0 if denom == 0 else float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
    bpm = float(np.clip(60 * sr / ((lags[i] + delta) * hop), bpm_lo, bpm_hi))
    return bpm, confidence


class TempoTracker:
    """스트리밍 템포 추정. 측정이 채택될 때만 bpm이 변한다 (멈추면 유지)."""

    def __init__(self, sr, base_bpm, hop=256, ratio_range=(0.7, 1.4), window_s=4.0,
                 update_s=0.25, tau_s=1.0, prior_sigma_oct=0.3, min_crest=2.5,
                 min_confidence=0.1, max_delay_s=0.5, min_delay_conf=6.0, wave_s=2.0,
                 deadband=0.005):
        self.sr = sr
        self.hop = hop
        self.base_bpm = base_bpm
        self.bpm_lo = base_bpm * ratio_range[0]
        self.bpm_hi = base_bpm * ratio_range[1]
        self.prior_sigma_oct = prior_sigma_oct
        self.min_crest = min_crest
        self.min_confidence = min_confidence
        self.alpha = 1 - math.exp(-update_s / tau_s)
        self.onset = OnsetStrength(sr, hop=hop)
        self._ring = np.zeros(round(window_s * sr / hop))
        self._update_frames = round(update_s * sr / hop)
        self._since = 0
        self._frames = 0
        self.bpm = float(base_bpm)
        self.confidence = 0.0
        self.measurements = 0
        self.max_delay_s = max_delay_s
        self.min_delay_conf = min_delay_conf
        self.deadband = deadband
        self.playback_bpm = None     # 엔진이 매 루프 갱신
        self.bleed_delay_s = None
        self.bleed_gain = 0.0
        self._ref_onset = OnsetStrength(sr, hop=hop)
        self._ref_ring = np.zeros(len(self._ring))
        self._ref_frames = 0
        self._mic_samples = 0        # 두 스트림의 시작을 같은 시각으로 보고 누적 길이로 정렬
        self._ref_samples = 0
        self._mic_wave = np.zeros(round(wave_s * sr), dtype=np.float32)
        self._ref_wave = np.zeros(round(wave_s * sr), dtype=np.float32)
        self._delays = []

    @staticmethod
    def _push_wave(wave, mono):
        mono = np.asarray(mono, dtype=np.float32)
        return np.concatenate([wave[len(mono):], mono])[-len(wave):]

    def process_ref(self, mono: np.ndarray) -> None:
        """앱이 내보낸 소리(모노). 마이크로 새어 들어온 몫을 빼는 데 쓴다."""
        for v in self._ref_onset.process(mono):
            self._ref_ring[:-1] = self._ref_ring[1:]
            self._ref_ring[-1] = v
            self._ref_frames += 1
        self._ref_wave = self._push_wave(self._ref_wave, mono)
        self._ref_samples += len(mono)

    def process(self, mono: np.ndarray) -> None:
        self._mic_wave = self._push_wave(self._mic_wave, mono)
        self._mic_samples += len(mono)
        for v in self.onset.process(mono):
            self._ring[:-1] = self._ring[1:]
            self._ring[-1] = v
            self._since += 1
            self._frames += 1
            if self._since >= self._update_frames:
                self._since = 0
                self._measure()

    def _measure(self) -> None:
        # 링이 한 번 다 차기 전에는 0 구간과 신호 구간의 경계가 crest·ACF를 속인다
        if self._frames < len(self._ring):
            return
        o = self._ring.copy()
        if self._ref_frames > 0:
            o = self._cancel_bleed(o)
        if o.max() <= 1e-9:
            return
        if o.max() / (o.mean() + 1e-12) < self.min_crest:
            return
        res = _acf_peak_bpm(o, self.sr, self.hop, self.bpm_lo, self.bpm_hi,
                            self.bpm, self.prior_sigma_oct)
        if res is None or res[1] < self.min_confidence:
            return
        bpm_meas, self.confidence = res
        # 재생 템포와 거의 같은 측정은 자기 소리일 수 있어 버린다
        if (self.playback_bpm is not None
                and abs(bpm_meas - self.playback_bpm) < self.deadband * self.playback_bpm):
            return
        self.bpm += self.alpha * (bpm_meas - self.bpm)
        self.measurements += 1

    def _cancel_bleed(self, o):
        k, conf = estimate_delay(self._mic_wave, self._ref_wave, round(self.max_delay_s * self.sr))
        if conf >= self.min_delay_conf:
            # 두 파형 버퍼의 끝이 서로 다른 시각이면 그만큼 빼서 실제 지연으로
            k -= self._ref_samples - self._mic_samples
            self._delays = (self._delays + [k])[-5:]
            self.bleed_delay_s = float(np.median(self._delays)) / self.sr
        if self.bleed_delay_s is None:
            return o
        W = len(o)
        # 측정은 마이크 블록 중간에 일어나 참조 링이 그만큼 앞서 있다
        d = round(self.bleed_delay_s * self.sr / self.hop) + self._ref_frames - self._frames
        if not 0 <= d < W:
            return o
        hann5 = np.hanning(5)
        rs = np.convolve(self._ref_ring, hann5 / hann5.sum(), mode="same")
        shifted = np.zeros(W)
        shifted[d:] = rs[:W - d]
        om = o - o.mean()
        sm = shifted - shifted.mean()
        g = max(0.0, float(np.dot(om, sm) / (np.dot(sm, sm) + 1e-12)))
        self.bleed_gain = g
        return np.maximum(o - g * shifted, 0)


def estimate_bpm(mono, sr, lo=60.0, hi=200.0, prior_bpm=110.0, prior_sigma_oct=0.6) -> float:
    """곡 전체에서 BPM 하나를 추정 (오프라인)."""
    o = OnsetStrength(sr, hop=256).process(mono)
    if len(o) == 0 or o.max() <= 1e-9:
        raise ValueError("no onsets")
    res = _acf_peak_bpm(o, sr, 256, lo, hi, prior_bpm, prior_sigma_oct)
    if res is None:
        raise ValueError("no onsets")
    return res[0]
