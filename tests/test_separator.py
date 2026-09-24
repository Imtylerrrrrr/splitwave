import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest

pytest.importorskip("demucs.api")

from common import find_ffmpeg  # noqa: E402
import separator  # noqa: E402

FFMPEG = find_ffmpeg()
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg 없음")

SR = 44100


def make_sine_wav(path: Path, seconds: float = 3.0, freq: float = 440.0) -> Path:
    n = int(seconds * SR)
    frames = bytearray()
    for i in range(n):
        v = int(12000 * math.sin(2 * math.pi * freq * i / SR))
        frames += struct.pack("<hh", v, v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))
    return path


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def test_decode_wav_shape(tmp_path):
    src = make_sine_wav(tmp_path / "s.wav", seconds=2.0)
    wav = separator.decode_with_ffmpeg(str(src), FFMPEG)
    assert tuple(wav.shape[:1]) == (2,)
    assert abs(wav.shape[1] - 2 * SR) < 100
    assert str(wav.dtype) == "torch.float32"


def test_decode_m4a(tmp_path):
    """다운로드 탭 기본 포맷(m4a)이 디코드되는지."""
    src = make_sine_wav(tmp_path / "s.wav", seconds=2.0)
    m4a = tmp_path / "s.m4a"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-c:a", "aac", str(m4a)], check=True)
    wav = separator.decode_with_ffmpeg(str(m4a), FFMPEG)
    assert abs(wav.shape[1] - 2 * SR) < 5000  # aac 인코더 지연분 허용


def test_decode_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(RuntimeError, match="오디오 디코드 실패"):
        separator.decode_with_ffmpeg(str(bad), FFMPEG)


def test_separate_wav_two_stems_with_progress(tmp_path):
    src = make_sine_wav(tmp_path / "song.wav", seconds=3.0)
    out = tmp_path / "song_stems"
    seen = []
    saved = separator.separate(
        str(src), ["vocals", "drums"], str(out), "wav", FFMPEG,
        on_progress=lambda frac, text: seen.append((frac, text)),
    )
    assert sorted(Path(p).name for p in saved) == ["드럼.wav", "보컬.wav"]
    for p in saved:
        assert abs(wav_seconds(Path(p)) - 3.0) < 0.1
    fracs = [f for f, _ in seen]
    assert fracs[0] == 0.0 and fracs[-1] == 1.0
    assert all(0.0 <= f <= 1.0 for f in fracs)
    assert fracs == sorted(fracs)  # 진행률은 뒤로 가지 않는다


def test_separate_mp3_with_key_shift(tmp_path):
    src = make_sine_wav(tmp_path / "song.wav", seconds=3.0)
    out = tmp_path / "song_stems"
    saved = separator.separate(str(src), ["bass"], str(out), "mp3", FFMPEG, semitones=2)
    assert [Path(p).name for p in saved] == ["베이스 (키+2).mp3"]
    assert Path(saved[0]).stat().st_size > 1000
    assert list(out.glob("*.wav")) == []  # 임시 wav가 남지 않는다


def test_separate_rejects_bad_args(tmp_path):
    src = make_sine_wav(tmp_path / "song.wav", seconds=1.0)
    with pytest.raises(ValueError):
        separator.separate(str(src), ["vocals"], str(tmp_path / "o"), "flac", FFMPEG)
    with pytest.raises(ValueError):
        separator.separate(str(src), ["strings"], str(tmp_path / "o"), "wav", FFMPEG)
    with pytest.raises(RuntimeError, match="FFmpeg"):
        separator.separate(str(src), ["vocals"], str(tmp_path / "o"), "wav", None)


def test_translate_stem_error():
    assert "메모리" in separator.translate_stem_error(RuntimeError("CUDA out of memory"))
    assert "읽을 수 없는" in separator.translate_stem_error(RuntimeError("오디오 디코드 실패: x"))
    assert "스템 분리에 실패" in separator.translate_stem_error(RuntimeError("weird"))
