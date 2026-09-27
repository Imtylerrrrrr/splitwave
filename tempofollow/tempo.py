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
                 min_confidence=0.1):
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

    def process(self, mono: np.ndarray) -> None:
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
        if o.max() <= 1e-9:
            return
        if o.max() / (o.mean() + 1e-12) < self.min_crest:
            return
        res = _acf_peak_bpm(o, self.sr, self.hop, self.bpm_lo, self.bpm_hi,
                            self.bpm, self.prior_sigma_oct)
        if res is None or res[1] < self.min_confidence:
            return
        bpm_meas, self.confidence = res
        self.bpm += self.alpha * (bpm_meas - self.bpm)
        self.measurements += 1


def estimate_bpm(mono, sr, lo=60.0, hi=200.0, prior_bpm=110.0, prior_sigma_oct=0.6) -> float:
    """곡 전체에서 BPM 하나를 추정 (오프라인)."""
    o = OnsetStrength(sr, hop=256).process(mono)
    if len(o) == 0 or o.max() <= 1e-9:
        raise ValueError("no onsets")
    res = _acf_peak_bpm(o, sr, 256, lo, hi, prior_bpm, prior_sigma_oct)
    if res is None:
        raise ValueError("no onsets")
    return res[0]
