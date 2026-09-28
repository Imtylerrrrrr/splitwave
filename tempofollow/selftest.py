# -*- coding: utf-8 -*-
"""GUI 없이 tempofollow 번들이 멀쩡한지 확인. CI 가 빌드 직후 exe 로 실행한다.
0 = 정상. 오디오 스트림은 열지 않는다 (마이크·스피커 사용 금지)."""

import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from common import find_ffmpeg
from tempofollow.engine import SR, decode
from tempofollow.stretch import WSOLA
from tempofollow.tempo import TempoTracker, estimate_bpm


def _click_track(bpm: float, seconds: float, sr: int) -> np.ndarray:
    """bpm, seconds 길이의 모노 클릭 트랙 (-1..1)."""
    y = np.zeros(int(seconds * sr))
    n = int(0.005 * sr)
    burst = 0.8 * np.exp(-np.linspace(0.0, 5.0, n))
    period = 60.0 / bpm * sr
    t = 0.0
    while int(t) + n <= len(y):
        y[int(t):int(t) + n] += burst
        t += period
    return y


def selftest() -> int:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("selftest: ffmpeg not found", file=sys.stderr)
        return 1

    bpm = 120.0
    seconds = 4.0
    click = _click_track(bpm, seconds, SR)
    pcm16 = (np.clip(click, -1.0, 1.0) * 32767).astype(np.int16)

    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = str(Path(tmpdir) / "click.wav")
        with wave.open(wav_path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SR)
            wav_file.writeframes(pcm16.tobytes())
        try:
            audio = decode(wav_path, ffmpeg)
        except Exception as e:
            print(f"selftest: decode failed: {e}", file=sys.stderr)
            return 1

    duration_s = len(audio) / SR
    if abs(duration_s - seconds) > 0.01 * seconds:
        print(f"selftest: decoded duration {duration_s:.3f}s, expected {seconds:.3f}s",
              file=sys.stderr)
        return 1

    mono = audio.mean(axis=1)

    try:
        bpm_est = estimate_bpm(mono, SR)
    except Exception as e:
        print(f"selftest: estimate_bpm failed: {e}", file=sys.stderr)
        return 1
    if abs(bpm_est - bpm) > 0.02 * bpm:
        print(f"selftest: estimated bpm {bpm_est:.2f}, expected {bpm:.2f}", file=sys.stderr)
        return 1

    try:
        stretcher = WSOLA(audio)
        for _ in range(5):
            chunk = stretcher.next_chunk(1.1)
            if chunk is None:
                break
            if not np.isfinite(chunk).all():
                print("selftest: WSOLA produced a non-finite chunk", file=sys.stderr)
                return 1
    except Exception as e:
        print(f"selftest: WSOLA failed: {e}", file=sys.stderr)
        return 1

    try:
        tracker = TempoTracker(SR, bpm)
        block = 480
        for i in range(0, len(mono), block):
            tracker.process(mono[i:i + block])
        if not np.isfinite(tracker.bpm):
            print("selftest: TempoTracker.bpm is not finite", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"selftest: TempoTracker failed: {e}", file=sys.stderr)
        return 1

    try:
        import sounddevice as sd
        sd.query_devices()
    except Exception as e:
        print(f"selftest: sounddevice query_devices failed: {e}", file=sys.stderr)
        return 1

    print("selftest: tempofollow ok")
    return 0
