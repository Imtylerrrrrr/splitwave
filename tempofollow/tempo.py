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


def estimate_delay(mic, ref, max_delay, sr, min_delay_s=0.005):
    """GCC-PHAT. mic[t] ≈ ref[t - k]인 k(샘플)와 신뢰도(피크 / RMS).

    Hann 창과 100 Hz~8 kHz 대역 제한으로 구간 가장자리 누설이 만드는 lag 0 피크를 막는다."""
    w = np.hanning(len(mic))
    n = 1 << (len(mic) + len(ref) - 1).bit_length()
    R = np.fft.rfft(mic * w, n) * np.conj(np.fft.rfft(ref * np.hanning(len(ref)), n))
    f = np.fft.rfftfreq(n, 1 / sr)
    R = np.where((f >= 100) & (f <= 8000), R / (np.abs(R) + 1e-12), 0)
    c = np.fft.irfft(R, n)[: max_delay + 1]
    lo = int(min_delay_s * sr)
    k = lo + int(np.argmax(c[lo:]))
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
    """스트리밍 템포 추정. 측정이 채택될 때만 bpm이 변한다 (멈추면 유지).

    process_ref로 앱이 내보낸 소리를 주면 마이크로 새어 든 몫을 스펙트럼에서 빼고,
    마이크 온셋 대부분이 자기 소리인 창은 측정하지 않는다."""

    def __init__(self, sr, base_bpm, hop=256, n_fft=1024, ratio_range=(0.7, 1.4), window_s=4.0,
                 update_s=0.25, tau_s=0.5, prior_sigma_oct=0.1, min_crest=2.5,
                 min_confidence=0.3, deadband=0.005, beta=2.0, tail=0.9, lam=0.999,
                 max_delay_s=0.8, min_delay_conf=4.0, floor=0.003, min_frac=0.4, gamma=5.0):
        self.sr = sr
        self.hop = hop
        self.n_fft = n_fft
        self.base_bpm = base_bpm
        self.bpm_lo = base_bpm * ratio_range[0]
        self.bpm_hi = base_bpm * ratio_range[1]
        self.prior_sigma_oct = prior_sigma_oct
        self.min_crest = min_crest
        self.min_confidence = min_confidence
        self.deadband = deadband
        self.beta = beta
        self.tail = tail
        self.lam = lam
        self.min_delay_conf = min_delay_conf
        self.floor = floor
        self.min_frac = min_frac
        self.gamma = gamma
        self._cands = []    # 최근 2초(8회)의 측정 후보. 게이트에 걸린 회차는 None
        self.alpha = 1 - math.exp(-update_s / tau_s)
        self.bpm = float(base_bpm)
        self.confidence = 0.0
        self.measurements = 0
        self.playback_bpm = None     # 엔진이 매 루프 갱신
        self.bleed_delay_s = None
        self.clean_frac = 1.0
        W = round(window_s * sr / hop)
        self._ring = np.zeros(W)        # 상쇄 후 플럭스
        self._raw_ring = np.zeros(W)    # 원본 마이크 플럭스
        self._update_frames = round(update_s * sr / hop)
        self._gcc_frames = round(0.5 * sr / hop)
        self._hold_samples = 8 * sr      # 출력이 들리기 시작한 뒤 지연을 찾으려 기다리는 한도
        self._ref_active = 0             # 무음이 아닌 출력 샘플 수
        self._cancel_frames = 0          # 상쇄가 켜진 채 처리한 연속 프레임 수
        self._frames = self._since = self._gcc_since = 0
        # 두 스트림은 같은 시각에 시작했다고 보고 누적 샘플 수(절대 위치)로 맞춘다
        self._keep = int((max_delay_s + 2.5) * sr)
        self._mb = np.zeros(self._keep, np.float32)   # 끝이 절대 위치 _mic_total
        self._rb = np.zeros(self._keep, np.float32)   # 끝이 절대 위치 _ref_total
        self._mic_total = self._ref_total = 0
        self._next_end = hop                          # 다음 마이크 프레임의 끝 절대 위치
        self._max_delay = int(max_delay_s * sr)
        self._delays = []
        self._delay = None
        self._win = np.hanning(n_fft)
        nb = n_fft // 2 + 1
        self._prev = np.zeros(nb)
        self._prev_raw = np.zeros(nb)
        self._Re = np.zeros(nb)
        self._mm = np.zeros(nb)
        self._mr = np.zeros(nb)
        self._cov = np.zeros(nb)
        self._var = np.zeros(nb)
        self._n = np.zeros(nb)    # 빈별 학습 프레임 수
        self._scale = floor

    def process_ref(self, mono: np.ndarray) -> None:
        """앱이 내보낸 소리(모노). 마이크로 새어 들어온 몫을 빼는 데 쓴다."""
        mono = np.asarray(mono, dtype=np.float32)
        self._rb = np.concatenate([self._rb[len(mono):], mono])[-self._keep:]
        self._ref_total += len(mono)
        if len(mono) and np.abs(mono).max() > 1e-6:
            self._ref_active += len(mono)

    def process(self, mono: np.ndarray) -> None:
        mono = np.asarray(mono, dtype=np.float32)
        step = self.sr // 4    # 버퍼보다 긴 블록도 앞부분을 잃지 않게 나눠 넣는다
        for i in range(0, len(mono), step):
            piece = mono[i:i + step]
            self._mb = np.concatenate([self._mb[len(piece):], piece])
            self._mic_total += len(piece)
            self._run()

    def _run(self) -> None:
        while self._next_end <= self._mic_total:
            end = self._next_end
            ref = None
            if self._ref_total > 0 and self._delay is not None:
                e2 = end - self._delay
                if self._ref_total < e2 and self._mic_total - end <= self.sr:
                    return    # 이 프레임에 겹치는 출력이 아직 안 왔다: 미룬다
                s = e2 - self.n_fft - (self._ref_total - self._keep)
                if e2 - self.n_fft >= 0 and s >= 0 and self._ref_total >= e2:
                    ref = self._rb[s:s + self.n_fft]
            self._frame(end, ref)
            self._next_end += self.hop

    def _frame(self, end, ref) -> None:
        m0 = end - self.n_fft - (self._mic_total - self._keep)
        x = self._mb[m0:m0 + self.n_fft]
        Mm = np.abs(np.fft.rfft(x * self._win))
        if ref is not None:
            Mr = np.abs(np.fft.rfft(ref * self._win))
            # 이득은 출력이 직접 들리는 빈(잔향 꼬리보다 큰 빈)에서만 배운다.
            # 꼬리 구간까지 넣으면 잔향이 적은 방에서 이득이 작게 나와 상쇄가 약해진다
            act = Mr >= self.tail * self._Re
            self._Re = np.maximum(Mr, self.tail * self._Re)    # 잔향 꼬리 포락선
            self._cancel_frames += 1
            self._n = self._n + act
            lam = np.minimum(self.lam, 1 - 1 / (self._n + 1))      # 처음엔 누적 평균으로 빨리 수렴
            mm = np.where(act, lam * self._mm + (1 - lam) * Mm, self._mm)
            mr = np.where(act, lam * self._mr + (1 - lam) * Mr, self._mr)
            self._cov = np.where(act, lam * self._cov + (1 - lam) * (Mm - mm) * (Mr - mr), self._cov)
            self._var = np.where(act, lam * self._var + (1 - lam) * (Mr - mr) ** 2, self._var)
            self._mm, self._mr = mm, mr
            G = np.clip(self._cov / (self._var + 1e-12), 0, None)
            Mc = np.maximum(Mm - self.beta * G * self._Re, 0)
        else:
            self._cancel_frames = 0
            Mc = Mm
        # 음량 인식 압축: 최근 큰 소리 기준이라 작은 잔류·잡음은 온셋이 거의 안 생긴다
        rms = float(np.sqrt(np.mean(x ** 2)))
        self._scale = max(self._scale * 0.9995, rms, self.floor)
        S = np.log1p(self.gamma * Mc / self._scale)
        Sr = np.log1p(self.gamma * Mm / self._scale)
        v = np.maximum(S - self._prev, 0).sum()
        self._prev = S
        vr = np.maximum(Sr - self._prev_raw, 0).sum()
        self._prev_raw = Sr
        self._ring[:-1] = self._ring[1:]
        self._ring[-1] = v
        self._raw_ring[:-1] = self._raw_ring[1:]
        self._raw_ring[-1] = vr
        self._frames += 1
        self._since += 1
        self._gcc_since += 1
        if self._ref_total > 0 and self._gcc_since >= self._gcc_frames:
            self._gcc_since = 0
            self._update_delay(end)
        if self._since >= self._update_frames:
            self._since = 0
            self._measure()

    def _update_delay(self, end) -> None:
        n = 2 * self.sr
        end = min(end, self._ref_total)   # 출력 스트림이 마이크보다 늦게 도착해도 공통 구간으로 추정
        ms = end - n - (self._mic_total - self._keep)
        rs = end - n - (self._ref_total - self._keep)
        if ms < 0 or rs < 0:
            return    # 두 버퍼가 같은 2초 구간을 다 갖고 있지 않다
        r = self._rb[rs:rs + n]
        if np.abs(r).max() <= 1e-6:
            return
        k, conf = estimate_delay(self._mb[ms:ms + n], r, self._max_delay, self.sr)
        if conf < self.min_delay_conf:
            return
        self._delays = (self._delays + [k])[-9:]
        med = float(np.median(self._delays))
        # 실제 블리드는 매번 같은 지연이 나오고, 블리드가 없으면 추정이 흩어진다
        # 일치하지 않으면 마지막 유효값을 유지한다 (물리적 지연은 세션 중 안 변하고,
        # 블리드가 없어지면 이득이 0으로 수렴해 상쇄가 저절로 꺼진다)
        if sum(abs(d - med) <= 0.002 * self.sr for d in self._delays) >= 5:
            self._delay = int(med)
            self.bleed_delay_s = self._delay / self.sr

    def _measure(self) -> None:
        cand = self._candidate()
        self._cands = (self._cands + [cand])[-8:]
        good = [c for c in self._cands if c is not None]
        if cand is None or len(good) < 6:
            return
        # 드럼은 연속 측정이 서로 일치하고, 드럼 아닌 소리·주변 소음은 흩어진다
        med = float(np.median(good))
        if sum(abs(c - med) < 0.03 * med for c in good) < 6:
            return
        # 재생 템포와 거의 같은 측정은 자기 소리일 수 있어 버린다
        if self.playback_bpm and abs(med - self.playback_bpm) < self.deadband * self.playback_bpm:
            return
        self.bpm += self.alpha * (med - self.bpm)
        self.measurements += 1

    def _candidate(self):
        """이번 창의 템포 후보. 게이트에 걸리면 None."""
        # 링이 한 번 다 차기 전에는 0 구간과 신호 구간의 경계가 crest·ACF를 속인다
        if self._frames < len(self._ring):
            return None
        if self._delay is None:
            if 0 < self._ref_active < self._hold_samples:
                return None    # 출력이 막 들리기 시작했다: 새어 드는지(지연) 먼저 확인
        elif self._cancel_frames < len(self._ring):
            return None        # 링에 상쇄 전 프레임이 아직 남아 있다
        o = self._ring.copy()
        if self._ref_total > 0:
            self.clean_frac = float(o.sum() / (self._raw_ring.sum() + 1e-12))
            if self.clean_frac < self.min_frac:
                return None    # 마이크 온셋 대부분이 자기 소리
        if o.max() <= 1e-9:
            return None
        if o.max() / (o.mean() + 1e-12) < self.min_crest:
            return None
        res = _acf_peak_bpm(o, self.sr, self.hop, self.bpm_lo, self.bpm_hi,
                            self.bpm, self.prior_sigma_oct)
        if res is None or res[1] < self.min_confidence:
            return None
        self.confidence = res[1]
        return res[0]


def estimate_bpm(mono, sr, lo=60.0, hi=200.0, prior_bpm=110.0, prior_sigma_oct=0.6) -> float:
    """곡 전체에서 BPM 하나를 추정 (오프라인)."""
    o = OnsetStrength(sr, hop=256).process(mono)
    if len(o) == 0 or o.max() <= 1e-9:
        raise ValueError("no onsets")
    res = _acf_peak_bpm(o, sr, 256, lo, hi, prior_bpm, prior_sigma_oct)
    if res is None:
        raise ValueError("no onsets")
    return res[0]
