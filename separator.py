# -*- coding: utf-8 -*-
"""Demucs(htdemucs_6s)로 스템을 분리한다. UI 의존 없음 — GUI 없이 단독 호출·테스트 가능.

흐름: ffmpeg로 입력을 44.1kHz 스테레오 float32로 디코드 → Separator.separate_tensor
     → 체크된 스템만 wav/mp3로 저장 (키 조정이 있으면 ffmpeg로 재인코딩).
demucs/torch 는 이 파일에서만 import 한다. (라이트 버전엔 없으므로 함수 안에서 지연 import)
"""

import os
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

from common import pitch_filter, CODEC_BY_EXT

MODEL_NAME = "htdemucs_6s"
SAMPLE_RATE = 44100  # htdemucs 계열 모델의 샘플레이트

# demucs 스템 이름 → 파일명에 쓸 한국어 라벨
STEM_LABELS = {
    "vocals": "보컬",
    "drums": "드럼",
    "guitar": "기타",
    "piano": "건반",
    "bass": "베이스",
    "other": "그외",
}
STEM_ORDER = ["vocals", "drums", "guitar", "piano", "bass", "other"]   # UI 표시 순서
DEFAULT_STEMS = ["vocals", "drums", "guitar", "piano", "bass"]          # 기본 체크

ProgressFn = Callable[[float, str], None]   # (0.0~1.0, 상태 문구)


def _no_window_flags() -> int:
    # --noconsole 빌드에서 검은 콘솔 창이 뜨지 않도록
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def decode_with_ffmpeg(path: str, ffmpeg: str):
    """아무 오디오 파일이나 ffmpeg로 (2, n) float32 텐서로 디코드한다.
    demucs 자체 로더는 PATH의 ffmpeg/ffprobe에 의존해서 번들 환경에서 못 쓴다."""
    import torch

    cmd = [ffmpeg, "-v", "error", "-i", path, "-vn",
           "-f", "f32le", "-ac", "2", "-ar", str(SAMPLE_RATE), "-"]
    result = subprocess.run(cmd, capture_output=True, creationflags=_no_window_flags())
    if result.returncode != 0 or len(result.stdout) < 8:
        err = result.stderr.decode(errors="replace")[-300:]
        raise RuntimeError(f"오디오 디코드 실패: {err}")
    data = np.frombuffer(result.stdout, dtype=np.float32)
    data = data[: len(data) // 2 * 2].reshape(-1, 2).T   # (2, n)
    return torch.from_numpy(np.ascontiguousarray(data))


def _reencode(src: Path, dst: Path, semitones: int, ffmpeg: str) -> None:
    """키 조정 재인코딩. dst 확장자(.wav/.mp3)에 맞는 코덱을 쓴다."""
    codec = CODEC_BY_EXT[dst.suffix.lower()]
    cmd = [ffmpeg, "-y", "-v", "error", "-i", str(src), "-vn",
           "-af", pitch_filter(semitones), *codec, str(dst)]
    result = subprocess.run(cmd, capture_output=True, creationflags=_no_window_flags())
    if result.returncode != 0 or not dst.is_file():
        err = result.stderr.decode(errors="replace")[-300:]
        raise RuntimeError(f"키 조정(FFmpeg) 실패: {err}")


def separate(
    input_path: str,
    stems: list[str],
    out_dir: str,
    fmt: str,
    ffmpeg: str | None,
    semitones: int = 0,
    on_progress: ProgressFn | None = None,
) -> list[str]:
    """input_path 를 분리해 out_dir 에 저장하고, 저장된 파일 경로 목록을 돌려준다.

    stems: demucs 이름 목록 (STEM_LABELS 의 키). 저장 순서 = 이 목록 순서.
    fmt:   "wav" | "mp3"
    """
    if fmt not in ("wav", "mp3"):
        raise ValueError(f"지원하지 않는 포맷: {fmt}")
    unknown = [s for s in stems if s not in STEM_LABELS]
    if unknown:
        raise ValueError(f"알 수 없는 스템: {unknown}")
    if not stems:
        raise ValueError("저장할 스템이 없습니다.")
    if not ffmpeg:
        raise RuntimeError("스템 분리에는 FFmpeg가 필요한데 찾지 못했습니다.")

    report: ProgressFn = on_progress or (lambda frac, text: None)
    os.makedirs(out_dir, exist_ok=True)

    report(0.0, "모델 불러오는 중… (최초 1회는 다운로드, 약 80MB)")
    import demucs.api

    last = [0.0]   # 진행률이 뒤로 가지 않게

    def callback(info: dict) -> None:
        total = info.get("audio_length") or 0
        if not total or info.get("state") != "end":
            return
        frac = min(info.get("segment_offset", 0) / total, 1.0)
        frac = 0.10 + 0.80 * frac
        if frac > last[0]:
            last[0] = frac
            report(frac, f"🎛️ 분리 중… {(frac - 0.10) / 0.80 * 100:.0f}%")

    sep = demucs.api.Separator(model=MODEL_NAME, device="cpu",
                               progress=False, callback=callback)

    report(0.05, "오디오 읽는 중…")
    wav = decode_with_ffmpeg(input_path, ffmpeg)
    _, sources = sep.separate_tensor(wav, SAMPLE_RATE)

    report(0.90, "저장 중…")
    out = Path(out_dir)
    saved: list[str] = []
    for name in stems:
        label = STEM_LABELS[name]
        if semitones == 0:
            target = out / f"{label}.{fmt}"
            demucs.api.save_audio(sources[name], target,
                                  samplerate=sep.samplerate, bitrate=320)
        else:
            sign = f"+{semitones}" if semitones > 0 else str(semitones)
            target = out / f"{label} (키{sign}).{fmt}"
            tmp = out / f"{label}.tmp.wav"
            demucs.api.save_audio(sources[name], tmp, samplerate=sep.samplerate)
            try:
                _reencode(tmp, target, semitones, ffmpeg)
            finally:
                tmp.unlink(missing_ok=True)
        saved.append(str(target))

    report(1.0, f"✅ 완료: {len(saved)}개 스템 저장")
    return saved


def translate_stem_error(err: Exception) -> str:
    """스템 분리 단계의 예외를 한국어 안내로."""
    msg = str(err)
    low = msg.lower()
    if isinstance(err, MemoryError) or "out of memory" in low or "not enough memory" in low:
        return "메모리가 부족해요. 더 짧은 곡으로 시도하거나 다른 프로그램을 닫아 주세요."
    if "오디오 디코드 실패" in msg:
        return "읽을 수 없는 오디오 파일이에요. mp3·wav·m4a·flac을 넣어 주세요."
    if "ffmpeg" in low:
        return ("FFmpeg를 찾지 못했습니다.\n"
                "ffmpeg.exe를 프로그램과 같은 폴더에 넣어 주세요. (README 참고)")
    return f"스템 분리에 실패했습니다.\n사유: {msg[:300]}"
