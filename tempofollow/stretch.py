# -*- coding: utf-8 -*-
"""WSOLA 타임스트레치 (음높이 유지, 속도만 변경). numpy만 쓴다."""

import numpy as np


class WSOLA:
    """스트리밍 WSOLA. next_chunk(ratio)마다 hop 샘플을 낸다."""

    def __init__(self, audio: np.ndarray, frame: int = 2048, hop: int = 1024, tol: int = 512):
        if len(audio) < frame:
            raise ValueError("audio shorter than one frame")
        self.audio = audio
        self.frame = frame
        self.hop = hop
        self.tol = tol
        self.mono = audio.mean(axis=1)
        self.win = np.hanning(frame + 1)[:-1]   # periodic Hann: 50 % 겹침 합이 1
        self.in_pos = 0.0
        self.prev = None
        self.tail = np.zeros((hop, audio.shape[1]), dtype=np.float32)
        self.done = False
        self.flushed = False

    @property
    def position_samples(self) -> int:
        return 0 if self.prev is None else self.prev + self.hop

    @property
    def finished(self) -> bool:
        return self.done and self.flushed

    def next_chunk(self, ratio: float):
        if not self.done:
            p = self._pick(ratio)
            if p is not None:
                fr = self.audio[p:p + self.frame] * self.win[:, None]
                out = self.tail + fr[:self.hop]
                self.tail = fr[self.hop:].astype(np.float32)
                self.prev = p
                return out.astype(np.float32)
            self.done = True
        if not self.flushed:
            self.flushed = True
            return self.tail
        return None

    def _pick(self, ratio: float):
        """다음 프레임 시작 위치. 입력이 끝났으면 None."""
        if self.prev is None:
            return 0
        n_in, frame = len(self.mono), self.frame
        self.in_pos += self.hop * ratio
        center = round(self.in_pos)
        lo = max(0, center - self.tol)
        hi = min(n_in - frame, center + self.tol)
        ref_start = self.prev + self.hop
        if ref_start + frame > n_in or lo > hi:
            return None
        ref = self.mono[ref_start:ref_start + frame]
        seg = self.mono[lo:hi + frame]
        n = 1 << (len(seg) - 1).bit_length()
        c = np.fft.irfft(np.fft.rfft(seg, n) * np.conj(np.fft.rfft(ref, n)), n)[:hi - lo + 1]
        cs = np.concatenate([[0.0], np.cumsum(seg.astype(np.float64) ** 2)])
        e = cs[frame:frame + hi - lo + 1] - cs[:hi - lo + 1]
        score = c / np.sqrt(np.maximum(e, 0) + 1e-9)
        return lo + int(np.argmax(score))
