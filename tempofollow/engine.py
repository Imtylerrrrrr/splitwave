# -*- coding: utf-8 -*-
"""오디오 엔진: 디코드, 장치, 마이크 → 템포 추정 → WSOLA → 출력."""

import os
import queue
import subprocess
import threading
import time

import numpy as np
import sounddevice as sd

from common import find_ffmpeg
from tempofollow.stretch import WSOLA
from tempofollow.tempo import TempoTracker

SR = 44100          # 재생 샘플레이트 (디코드도 이 값)
HOP = 1024          # WSOLA hop = 출력 blocksize
AHEAD_S = 0.3       # 미리 채워 둘 출력 버퍼 길이 (비율 변화 반영 지연의 상한)
SLEW_PER_S = 0.08   # 초당 최대 비율 변화


def decode(path: str, ffmpeg: str) -> np.ndarray:
    """오디오 파일 → (n, 2) float32, 44.1 kHz."""
    cmd = [ffmpeg, "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", "44100", "-"]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(cmd, capture_output=True, creationflags=flags)
    if result.returncode != 0:
        raise RuntimeError(f"오디오 디코드 실패: {result.stderr.decode(errors='replace')[-300:]}")
    data = np.frombuffer(result.stdout, np.float32)
    return data[: len(data) // 2 * 2].reshape(-1, 2).copy()


def list_devices():
    """(inputs, outputs): 각각 (index, name) 목록."""
    devs = sd.query_devices()
    inputs = [(i, d["name"]) for i, d in enumerate(devs) if d["max_input_channels"] > 0]
    outputs = [(i, d["name"]) for i, d in enumerate(devs) if d["max_output_channels"] > 0]
    return inputs, outputs


def default_devices():
    in_idx, out_idx = sd.default.device
    return in_idx, out_idx


class _Resampler:
    """선형 보간 리샘플. 블록 경계 위상을 이어 간다."""

    def __init__(self, src_sr, dst_sr):
        self.step = src_sr / dst_sr
        self.pos = 0.0
        self.last = np.zeros(1, np.float32)

    def process(self, block):
        x = np.concatenate([self.last, block])
        idx = np.arange(self.pos, len(x) - 1, self.step)
        out = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
        consumed = len(x) - 1
        self.pos = (idx[-1] + self.step - consumed) if len(idx) else (self.pos - consumed)
        self.last = x[-1:]
        return out


class Engine:
    def __init__(self):
        self.audio = None
        self.duration_s = 0.0
        self.tracker = None
        self.stretcher = None
        self.base_bpm = 0.0
        self.ratio = 1.0
        self.level_db = -120.0
        self.playing = False
        self.finished = False
        self.underflows = 0
        self.error = None
        self._running = False
        self._streams = []
        self._threads = []

    def load(self, path: str) -> None:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("ffmpeg를 찾지 못했습니다. (README 참고)")
        self.audio = decode(path, ffmpeg)
        self.duration_s = len(self.audio) / SR

    def start(self, base_bpm, in_dev, out_dev, range_pct, wait_for_hit, hit_threshold_db):
        r = range_pct / 100
        self.base_bpm = base_bpm
        self.ratio = 1.0
        self.level_db = -120.0
        self.playing = not wait_for_hit
        self.finished = False
        self.underflows = 0
        self.error = None
        self._ring = np.zeros((SR * 2, 2), dtype=np.float32)
        self._lock = threading.Lock()
        self._w_idx = self._r_idx = self._count = 0
        self._produced_all = False
        self._queue = queue.Queue(maxsize=256)
        self._ref_queue = queue.Queue(maxsize=256)
        self._running = True
        try:
            mic_sr = int(sd.query_devices(in_dev)["default_samplerate"])
            self._resampler = _Resampler(mic_sr, SR)
            self.tracker = TempoTracker(SR, base_bpm, ratio_range=(1 - r, 1 + r))
            self.stretcher = WSOLA(self.audio)
            self._streams = [
                sd.InputStream(device=in_dev, channels=1, samplerate=mic_sr, blocksize=512,
                               dtype="float32", callback=self._in_cb),
                sd.OutputStream(device=out_dev, channels=2, samplerate=SR, blocksize=HOP,
                                dtype="float32", callback=self._out_cb),
            ]
            self._threads = [
                threading.Thread(target=self._guard, args=(self._analyze, wait_for_hit,
                                                           hit_threshold_db), daemon=True),
                threading.Thread(target=self._guard, args=(self._produce, r), daemon=True),
            ]
            for t in self._threads:
                t.start()
            for s in self._streams:
                s.start()
        except Exception as e:
            self.error = str(e)
            self.stop()

    def stop(self) -> None:
        self._running = False
        for s in self._streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._streams = []
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(timeout=2)
        self._threads = []
        self.playing = False

    def status(self) -> dict:
        t, w = self.tracker, self.stretcher
        return dict(
            bpm=t.bpm if t else self.base_bpm,
            confidence=t.confidence if t else 0.0,
            ratio=self.ratio,
            playback_bpm=self.base_bpm * self.ratio,
            position_s=w.position_samples / SR if w else 0.0,
            duration_s=self.duration_s,
            level_db=self.level_db,
            playing=self.playing,
            finished=self.finished,
            underflows=self.underflows,
            error=self.error,
            bleed_delay_ms=t.bleed_delay_s * 1000 if t and t.bleed_delay_s is not None else None,
            bleed_gain=t.bleed_gain if t else 0.0,
        )

    # ── 스트림 콜백 (오디오 스레드) ──
    def _in_cb(self, indata, frames, time_info, status):
        try:
            self._queue.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def _out_cb(self, outdata, frames, time_info, status):
        with self._lock:
            if self.playing and self._count >= frames:
                n = len(self._ring)
                idx = (self._r_idx + np.arange(frames)) % n
                outdata[:] = self._ring[idx]
                self._r_idx = (self._r_idx + frames) % n
                self._count -= frames
            else:
                if self.playing and self._produced_all:
                    self.finished = True    # 곡 끝까지 다 내보냄
                elif self.playing:
                    self.underflows += 1
                outdata.fill(0)
        # 내보낸 소리를 트래커에 알려 마이크로 새어 든 몫을 빼게 한다
        try:
            self._ref_queue.put_nowait(outdata.mean(axis=1).copy())
        except queue.Full:
            pass

    # ── 작업 스레드 ──
    def _guard(self, fn, *args):
        try:
            fn(*args)
        except Exception as e:
            self.error = str(e)
            self.stop()

    def _analyze(self, wait_for_hit, hit_threshold_db):
        while self._running:
            try:
                block = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            while True:
                try:
                    self.tracker.process_ref(self._ref_queue.get_nowait())
                except queue.Empty:
                    break
            self.tracker.process(self._resampler.process(block))
            peak_db = 20 * np.log10(np.max(np.abs(block)) + 1e-9)
            self.level_db = peak_db
            if wait_for_hit and not self.playing and peak_db > hit_threshold_db:
                self.playing = True

    def _produce(self, r):
        last = time.monotonic()
        while self._running:
            with self._lock:
                count = self._count
            if count >= AHEAD_S * SR:
                time.sleep(0.005)
                continue
            now = time.monotonic()
            dt, last = now - last, now
            target = float(np.clip(self.tracker.bpm / self.base_bpm, 1 - r, 1 + r))
            self.ratio += float(np.clip(target - self.ratio, -SLEW_PER_S * dt, SLEW_PER_S * dt))
            self.tracker.playback_bpm = self.base_bpm * self.ratio
            chunk = self.stretcher.next_chunk(self.ratio)
            if chunk is None:
                self._produced_all = True
                return
            with self._lock:
                n = len(self._ring)
                idx = (self._w_idx + np.arange(len(chunk))) % n
                self._ring[idx] = chunk
                self._w_idx = (self._w_idx + len(chunk)) % n
                self._count += len(chunk)
