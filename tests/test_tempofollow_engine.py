import threading

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("sounddevice")

from tempofollow.engine import HOP, SR, Engine
from tempofollow.stretch import WSOLA
from tempofollow.tempo import TempoTracker


def make_engine():
    """Engine.start 없이(스트림 없음) _phase_error 에 필요한 상태만 꽂는다."""
    e = Engine()
    e.follow_phase = True
    e.playing = True
    e.beats_ok = True
    e.ratio = 1.0
    e.tracker = TempoTracker(SR, 100)
    e.tracker.bpm = 100.0
    e.tracker.beat_end = 1.0 * SR
    e.tracker.beat_at = int(1.2 * SR)
    e.tracker._mic_total = int(1.3 * SR)
    e.stretcher = WSOLA(np.zeros((SR * 2, 2), np.float32))
    e.stretcher.in_pos = 0.0
    e.beats = np.array([0.5, 1.1, 1.7]) * SR
    e._written = 0
    e._emitted = 0
    e._consumed = 0
    e._device_delay = 0
    e._lock = threading.Lock()
    return e


def fold(x, period=0.6):
    return ((x + period / 2) % period) - period / 2


def test_phase_error_timeline():
    e = make_engine()
    # 다음 청크는 곡 위치 HOP 에서 시작해 출력 0 번째로 나가므로 곡 박 0.5 s 는 출력 0.5 s - HOP 에 나간다.
    # 드러머 박 1.0 s (주기 0.6 → 0.4 s 에도 박) 보다 0.1 - HOP/SR 늦다
    base = 0.5 - HOP / SR - 1.0
    assert abs(e._phase_error() - fold(base)) < 1e-6
    assert abs(fold(base) - 0.0768) < 0.001

    # 재생 전 무음 1초: 출력 전체가 1초 밀린다
    e._emitted = SR
    assert abs(e._phase_error() - fold(base + 1.0)) < 1e-6
    e._emitted = 0

    # 스피커 블리드로 잰 지연 0.1 s 가 장치 지연 대신 쓰인다
    e._device_delay = int(0.05 * SR)
    e.tracker._delay = int(0.1 * SR)
    assert abs(e._phase_error() - fold(base + 0.1)) < 1e-6
    e.tracker._delay = None
    assert abs(e._phase_error() - fold(base + 0.05)) < 1e-6


def test_phase_error_none_cases():
    e = make_engine()
    e.tracker.beat_at = e.tracker._mic_total - int(2.5 * SR)
    assert e._phase_error() is None
    e = make_engine()
    e.beats_ok = False
    assert e._phase_error() is None
    e = make_engine()
    e.playing = False
    assert e._phase_error() is None
    e = make_engine()
    e.follow_phase = False
    assert e._phase_error() is None
