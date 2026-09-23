# 스템 분리 기능 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 유튜브 오디오 다운로더에 Demucs(htdemucs_6s) 기반 스템 분리 탭을 추가하고, 라이트(다운로드만)·풀(스템 포함) 두 빌드를 CI에서 뽑는다.

**Architecture:** `main.py` 한 파일에 있던 UI 무관 헬퍼를 `common.py`로 옮기고, `App`을 `CTkTabview` 호스트로 바꾼다. 스템 탭 UI는 `stems_page.py`, Demucs 호출은 UI 의존 없는 `separator.py`. 풀/라이트는 코드가 같고 `import demucs` 가능 여부로만 갈린다.

**Tech Stack:** Python 3.12, customtkinter, yt-dlp, FFmpeg(번들), demucs>=4.1.0 + torch(CPU), pytest, PyInstaller (GitHub Actions windows-latest)

**Spec:** `docs/superpowers/specs/2026-09-24-stem-separation-design.md` — 본문과 마지막 "계획 작성 중 확인된 사실" 절을 **둘 다** 읽을 것. 충돌하면 후자가 우선.

## Global Constraints

- 파이썬 3.12 (CI와 맥 venv 동일). venv는 `.venv/`, 실행은 항상 `.venv/bin/python` / `.venv/bin/pytest`.
- 레포 루트: `/Users/tylerrr/Documents/GitHub/youtube-audio-downloader`. 모든 경로는 여기 기준.
- 기존 함수는 **내용 수정 없이 이동만**. 다운로드 탭의 동작은 변경 전과 동일해야 한다.
- 사용자 대면 문구는 전부 한국어, 기존 톤(이모지 + 해요체/합니다체 혼용 그대로) 유지.
- `demucs`/`torch`를 모듈 최상단에서 import하는 파일은 `separator.py` 하나뿐. `stems_page.py`는 `separator`를 함수 안에서 지연 import.
- 스템 파일명은 한국어 라벨: `보컬 드럼 기타 건반 베이스 그외` + 키 조정 시 ` (키+2)` 접미.
- 기본 체크 스템: `vocals, drums, guitar, piano, bass` (other는 기본 해제).
- 모델: `htdemucs_6s`, `device="cpu"`.
- 워커 스레드 → UI 갱신은 반드시 `app.after(0, …)` 경유 (기존 패턴).
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 한 줄. **push는 하지 않는다** (사용자가 한다).
- 테스트를 통과시키려고 테스트를 약화·삭제하지 않는다.

## Review Focus

스펙이 명시하진 않지만 실제 사용자가 부딪힐 입력·상황. 각 항목의 테스트는 해당 태스크에 들어 있다.

1. **m4a 입력** — 다운로드 탭이 기본으로 m4a를 만들므로 스템 탭의 가장 흔한 입력. ffmpeg 디코드 경로가 m4a를 처리해야 한다. → Task 2 `test_decode_m4a`.
2. **파일과 링크를 둘 다 넣은 경우** — 파일 우선, 링크 무시. 둘 다 비면 경고 후 아무 것도 안 함. → Task 4 `test_resolve_input_*`.
3. **스템을 하나도 체크 안 한 경우** — 시작 전에 경고, 워커 시작 안 함. → Task 4 `test_start_requires_stem`.
4. **키 조정 + mp3 조합** — 파일명 `보컬 (키+2).mp3`, 임시 wav가 남지 않아야 한다. → Task 2 `test_separate_mp3_with_key_shift`.
5. **라이트 환경에서 실행** — demucs 없어도 앱이 뜨고 스템 탭에 안내만 보인다. → Task 3 `test_lite_placeholder_when_demucs_missing` (monkeypatch로 import 실패 시뮬레이션).

---

### Task 0: 개발 환경 정비 (Python 3.12 venv, 의존성 파일, pytest)

**Files:**
- Create: `requirements-stems.txt`
- Create: `requirements-dev.txt`
- Modify: `.gitignore`
- Create: `tests/__init__.py` (빈 파일)

**Interfaces:**
- Produces: 이후 모든 태스크가 쓰는 `.venv/bin/pytest`, `demucs` import 가능한 환경.

- [ ] **Step 1: venv를 3.12로 재생성**

```bash
cd /Users/tylerrr/Documents/GitHub/youtube-audio-downloader
rm -rf .venv
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python --version
```
Expected: `Python 3.12.x`

- [ ] **Step 2: 의존성 파일 작성**

`requirements-stems.txt`:
```
# 풀 버전(스템 분리 포함). demucs 4.1.0+는 torchaudio 불필요.
# PyPI의 Windows/macOS torch 휠은 CPU 빌드라 별도 인덱스 없이 설치된다.
-r requirements.txt
demucs>=4.1.0
torch>=2.1
numpy
```

`requirements-dev.txt`:
```
pytest>=8
```

- [ ] **Step 3: `.gitignore`에 추가**

파일 끝에 덧붙인다:
```

# 풀 빌드용 Demucs 가중치 캐시 (CI가 만든다)
hf_home/

# macOS / pytest
.DS_Store
.pytest_cache/
```

- [ ] **Step 4: 설치 및 확인**

```bash
.venv/bin/pip install -q -r requirements-stems.txt -r requirements-dev.txt
.venv/bin/python -c "import demucs.api, torch, yt_dlp, customtkinter; print('ok', torch.__version__)"
which ffmpeg || echo "NO FFMPEG"
```
Expected: `ok 2.x.x`. ffmpeg가 없으면 `brew install ffmpeg` 후 재확인 (Task 2 테스트에 필요).
설치가 오래 걸린다(torch ~200MB). 실패하면 에러 마지막 5줄만 보고할 것.

- [ ] **Step 5: 빈 tests 패키지 만들고 커밋**

```bash
mkdir -p tests && touch tests/__init__.py
git add requirements-stems.txt requirements-dev.txt .gitignore tests/__init__.py
git commit -m "chore: Python 3.12 venv, stems/dev requirements, tests package

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 1: `common.py` 추출 (UI 무관 헬퍼 이동)

**Files:**
- Create: `common.py`
- Modify: `main.py` (이동한 구간 삭제 + import 추가)
- Test: `tests/test_common.py`

**Interfaces:**
- Produces (`common.py`, 모두 기존 `main.py`와 동일 시그니처):
  - `resource_path(relative: str) -> str`, `app_dir() -> str`, `find_ffmpeg() -> str | None`
  - `KEY_VALUES: list[str]`, `KEY_HELP: str`, `parse_key(label: str) -> int`, `pitch_filter(semitones: int) -> str`, `CODEC_BY_EXT: dict[str, list[str]]`, `shift_pitch(src: str, semitones: int, ffmpeg: str) -> str`
  - `YOUTUBE_RE`, `is_youtube_url(url: str) -> bool`, `is_playlist_url(url: str) -> bool`, `translate_error(err: Exception) -> str`
  - `collect_filepaths(info: dict) -> list[str]` (기존 `App._collect_filepaths` 스태틱메서드를 모듈 함수로)
  - `open_path(path: str) -> None` (기존 `App.open_folder`의 OS별 탐색기 열기 로직, 실패 시 `messagebox.showinfo("안내", f"폴더 위치: {path}")`)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_common.py`:
```python
import common


def test_parse_key():
    assert common.parse_key("0 (원본)") == 0
    assert common.parse_key("+2") == 2
    assert common.parse_key("-3") == -3


def test_pitch_filter_is_tempo_preserving():
    f = common.pitch_filter(12)  # 한 옥타브 위 → asetrate 96000, atempo 0.5
    assert "asetrate=96000" in f
    assert "atempo=0.500000" in f


def test_is_youtube_url():
    assert common.is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert common.is_youtube_url("youtu.be/abc")
    assert not common.is_youtube_url("https://example.com/x")


def test_collect_filepaths_skips_missing(tmp_path):
    real = tmp_path / "a.m4a"
    real.write_bytes(b"x")
    info = {"entries": [
        {"requested_downloads": [{"filepath": str(real)}]},
        {"requested_downloads": [{"filepath": str(tmp_path / "missing.m4a")}]},
        None,
    ]}
    assert common.collect_filepaths(info) == [str(real)]


def test_common_has_no_gui_imports():
    import sys
    assert "customtkinter" not in sys.modules or True  # common 자체는 아래에서 검사
    src = open(common.__file__, encoding="utf-8").read()
    assert "customtkinter" not in src
    assert "yt_dlp" not in src
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_common.py -q`
Expected: `ModuleNotFoundError: No module named 'common'`

- [ ] **Step 3: `common.py` 생성 — main.py에서 잘라 옮기기**

`main.py`에서 아래 구간을 **그대로 잘라내어**(내용 수정 금지) `common.py`에 붙인다. 줄 번호는 현재 `main.py` 기준(`git show HEAD:main.py`로 확인 가능):

| 옮길 구간 (main.py) | 내용 |
|---|---|
| 22–67 | `# 경로 / FFmpeg 탐색` 섹션: `resource_path`, `app_dir`, `find_ffmpeg` |
| 143–207 | `# 키 조정` 섹션: `KEY_VALUES`, `KEY_HELP`, `parse_key`, `pitch_filter`, `CODEC_BY_EXT`, `shift_pitch` |
| 210–251 | `# URL 검사 / 에러 한국어 변환` 섹션: `YOUTUBE_RE`, `is_youtube_url`, `is_playlist_url`, `translate_error` |
| 489–502 | `App._collect_filepaths` → 모듈 함수 `collect_filepaths(info)`로 (`@staticmethod` 제거, 들여쓰기 한 단계 내림) |
| 376–386 | `App.open_folder`의 본문 → 모듈 함수 `open_path(path)`로 (`self.save_dir` → `path`) |

`common.py` 머리 부분은 정확히 이렇게:
```python
# -*- coding: utf-8 -*-
"""main.py / stems_page.py / separator.py 가 공유하는 UI 무관 헬퍼.
GUI(customtkinter)나 yt_dlp를 여기서 import하지 않는다."""

import os
import re
import sys
import shutil
import subprocess
from pathlib import Path
from tkinter import messagebox
```
그 아래에 위 표의 구간을 순서대로 붙인다. `open_path`는 이렇게 된다:
```python
def open_path(path: str) -> None:
    """폴더를 OS 탐색기로 연다."""
    try:
        if os.name == "nt":
            os.startfile(path)  # Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        messagebox.showinfo("안내", f"폴더 위치: {path}")
```

- [ ] **Step 4: `main.py` 수정**

1. 상단 import 블록의 `import yt_dlp` 아래에 추가:
```python
from common import (
    find_ffmpeg, KEY_VALUES, KEY_HELP, parse_key, shift_pitch,
    is_youtube_url, is_playlist_url, translate_error,
    collect_filepaths, open_path,
)
```
2. `App.open_folder`를 이렇게 교체:
```python
    def open_folder(self):
        open_path(self.save_dir)
```
3. `_download_worker` 안의 `paths = self._collect_filepaths(info)` → `paths = collect_filepaths(info)`.
4. 이제 안 쓰는 import 정리: `grep -n "re\.\|shutil\." main.py` 결과가 비면 `import re`, `import shutil` 삭제. `resource_path`/`app_dir`가 main.py에 남아 있는지 `grep -n "resource_path\|app_dir" main.py`로 확인 — 남아 있으면 import 목록에 추가.

- [ ] **Step 5: 통과 확인 + 앱 import 스모크**

```bash
.venv/bin/pytest tests/test_common.py -q
.venv/bin/python -c "import main; print('main import ok')"
.venv/bin/python -m pyflakes main.py common.py 2>/dev/null || .venv/bin/pip install -q pyflakes && .venv/bin/python -m pyflakes main.py common.py
```
Expected: 5 passed, `main import ok`, pyflakes 출력 없음 (undefined name이 하나라도 나오면 이동에서 빠진 이름이다).

- [ ] **Step 6: 앱 수동 확인 (10초)**

`.venv/bin/python main.py` → 창이 뜨고, 저장 폴더 선택·폴더 열기 버튼이 동작하면 닫는다. (다운로드까지는 안 해도 됨.)

- [ ] **Step 7: 커밋**

```bash
git add common.py main.py tests/test_common.py
git commit -m "refactor: move UI-independent helpers from main.py to common.py

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `separator.py` — Demucs 스템 분리 (UI 없음)

**Files:**
- Create: `separator.py`
- Test: `tests/test_separator.py`

**Interfaces:**
- Consumes: `common.pitch_filter`, `common.CODEC_BY_EXT`, `common.find_ffmpeg`(테스트에서)
- Produces:
  - `MODEL_NAME = "htdemucs_6s"`, `SAMPLE_RATE = 44100`
  - `STEM_LABELS: dict[str, str]` (demucs 이름 → 한국어), `STEM_ORDER: list[str]`(UI 표시 순서), `DEFAULT_STEMS: list[str]`
  - `decode_with_ffmpeg(path: str, ffmpeg: str) -> torch.Tensor` shape `(2, n)` float32
  - `separate(input_path, stems, out_dir, fmt, ffmpeg, semitones=0, on_progress=None) -> list[str]`
  - `translate_stem_error(err: Exception) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_separator.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_separator.py -q`
Expected: `ModuleNotFoundError: No module named 'separator'`

- [ ] **Step 3: `separator.py` 작성**

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/test_separator.py -q -x`
Expected: 7 passed. **첫 실행은 HuggingFace에서 모델을 받느라 1~3분** 걸린다. 그 뒤로는 3초 음원 기준 테스트 하나에 5~15초.
콜백 dict 키가 스펙과 다르게 나오면(`segment_offset`/`audio_length`/`state`) `python -c "import demucs.apply, inspect; print(inspect.getsource(demucs.apply.apply_model))" | grep -n callback` 으로 실제 키를 확인해 맞춘다 — 테스트를 고치지 말 것.

- [ ] **Step 5: 커밋**

```bash
git add separator.py tests/test_separator.py
git commit -m "feat: Demucs htdemucs_6s stem separation module (no UI)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: `main.py` 탭 구조 + 라이트 안내 프레임 + `--selftest`

**Files:**
- Modify: `main.py` (`App.__init__`, `_build_ui`, `downloading` 플래그, `main()`)
- Create: `stems_page.py` (이 태스크에서는 `stems_available`, `LitePlaceholder`, `make_stems_tab`만; `StemsPage`는 Task 4)
- Test: `tests/test_app_tabs.py`

**Interfaces:**
- Consumes: `common.resource_path`, `separator.MODEL_NAME` (selftest에서 지연 import)
- Produces:
  - `App.busy: bool` (기존 `self.downloading` 대체 — 다운로드·스템 어느 쪽이든 작업 중이면 True)
  - `App.tabview: ctk.CTkTabview`, 탭 이름 `"다운로드"`, `"스템 분리"`
  - `App.stems_page` (`StemsPage` 또는 `LitePlaceholder`)
  - `App.folder_listeners: list[Callable[[str], None]]` — `choose_folder`가 새 경로로 호출
  - `stems_page.stems_available() -> bool`
  - `stems_page.make_stems_tab(parent, app) -> ctk.CTkFrame`
  - `main.configure_bundled_model_cache() -> None`, `main.selftest() -> int`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_app_tabs.py` — **이 파일의 테스트는 전부 "라이트 환경"을 흉내 낸다** (autouse 픽스처가 demucs import를 막음). 풀 환경 테스트는 Task 4의 `test_stems_page.py`.
```python
import builtins
import sys

import pytest

import stems_page


@pytest.fixture(autouse=True)
def lite_env(monkeypatch):
    """demucs 가 없는 라이트 환경 시뮬레이션."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "demucs" or name.startswith("demucs."):
            raise ImportError("no demucs (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for mod in [m for m in sys.modules if m == "demucs" or m.startswith("demucs.")]:
        monkeypatch.delitem(sys.modules, mod, raising=False)


def _make_app():
    """디스플레이가 없으면 skip."""
    import main
    try:
        app = main.App()
    except Exception as e:  # tkinter.TclError 등
        pytest.skip(f"GUI를 만들 수 없음: {e}")
    app.update()
    return app


def test_app_has_two_tabs():
    app = _make_app()
    try:
        assert app.tabview.tab("다운로드") is not None
        assert app.tabview.tab("스템 분리") is not None
        assert app.busy is False
        assert not hasattr(app, "downloading")
    finally:
        app.destroy()


def test_folder_listeners_called(tmp_path, monkeypatch):
    app = _make_app()
    try:
        got = []
        app.folder_listeners.append(got.append)
        monkeypatch.setattr("main.filedialog.askdirectory", lambda **kw: str(tmp_path))
        monkeypatch.setattr("main.save_settings", lambda s: None)
        app.choose_folder()
        assert got == [str(tmp_path)]
        assert app.save_dir == str(tmp_path)
    finally:
        app.destroy()


def test_lite_placeholder_when_demucs_missing():
    """demucs import가 실패하면 스템 탭엔 안내 프레임만."""
    assert stems_page.stems_available() is False
    app = _make_app()
    try:
        assert isinstance(app.stems_page, stems_page.LitePlaceholder)
    finally:
        app.destroy()


def test_selftest_lite():
    import main
    assert main.selftest() == 0
```

`tests/test_selftest.py` — 실제(풀) 환경에서 selftest가 모델까지 로드하는지:
```python
import pytest

pytest.importorskip("demucs.api")


def test_selftest_full_loads_model(capsys):
    import main
    assert main.selftest() == 0
    assert "full build ok" in capsys.readouterr().out
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_app_tabs.py -q`
Expected: `ModuleNotFoundError: No module named 'stems_page'`

- [ ] **Step 3: `stems_page.py` 생성 (안내 프레임까지만)**

```python
# -*- coding: utf-8 -*-
"""스템 분리 탭.
demucs 가 설치돼 있으면 StemsPage, 없으면(라이트 버전) LitePlaceholder 를 만든다.
demucs/torch 는 여기서 최상단 import 하지 않는다 — 라이트 환경에서도 이 모듈은 로드돼야 한다."""

import customtkinter as ctk


def stems_available() -> bool:
    """풀 버전 여부는 오직 demucs import 가능 여부로 판단한다."""
    try:
        import demucs.api  # noqa: F401
    except ImportError:
        return False
    return True


LITE_NOTICE = (
    "🎛️ 스템 분리는 풀 버전에서 지원돼요.\n\n"
    "• 풀 버전(zip)을 받아서 실행하거나\n"
    "• 소스로 실행 중이라면 터미널에서\n"
    "    pip install -r requirements-stems.txt\n"
    "  를 실행한 뒤 프로그램을 다시 켜 주세요.\n\n"
    "(풀 버전은 PyTorch가 들어 있어 수백 MB예요)"
)


class LitePlaceholder(ctk.CTkFrame):
    """라이트 버전에서 스템 탭에 보여줄 안내."""

    def __init__(self, parent):
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="both", expand=True)
        ctk.CTkLabel(
            self, text=LITE_NOTICE, justify="left", anchor="w",
            font=ctk.CTkFont(size=13),
        ).pack(fill="x", padx=20, pady=30)


def make_stems_tab(parent, app) -> ctk.CTkFrame:
    if not stems_available():
        return LitePlaceholder(parent)
    from stems_page import StemsPage   # 같은 모듈. Task 4 에서 클래스가 추가된다
    return StemsPage(parent, app)
```
> 이 태스크 시점엔 `StemsPage`가 아직 없다. 자기 모듈을 import하는 형태라 pyflakes는 통과하고, 풀 환경에서 앱을 띄우면 `ImportError: cannot import name 'StemsPage'`가 나는 게 이 시점엔 정상이다 (Task 4가 채운다). 그래서 이 태스크의 GUI 테스트는 전부 라이트 시뮬레이션이다.

- [ ] **Step 4: `main.py` 수정**

(a) 상단 docstring 아래 import에 `from common import (…)` 목록에 `resource_path` 추가.

(b) `App.__init__`에서:
```python
        self.geometry("560x700")
```
→ `"560x780"`. 그리고
```python
        self.ffmpeg_path = find_ffmpeg()
        self.downloading = False
```
→
```python
        self.ffmpeg_path = find_ffmpeg()
        self.busy = False   # 다운로드/스템 분리 중 하나라도 돌고 있으면 True
        self.folder_listeners = []   # 저장 폴더가 바뀌면 호출할 콜백들 (스템 탭이 등록)
```

(c) 파일 전체에서 `self.downloading` → `self.busy` 치환 (총 8곳 안팎):
```bash
sed -i '' 's/self\.downloading/self.busy/g' main.py
grep -c "self.busy" main.py   # 8 이상
```

(d) `_build_ui`를 탭 호스트로 바꾸고 기존 본문은 `_build_download_tab(root)`로 옮긴다:
```python
    # ── UI 구성 ──
    def _build_ui(self):
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        dl_tab = self.tabview.add("다운로드")
        stems_tab = self.tabview.add("스템 분리")
        self._build_download_tab(dl_tab)

        from stems_page import make_stems_tab   # 지연 import (라이트/풀 공통)
        self.stems_page = make_stems_tab(stems_tab, self)

    def _build_download_tab(self, root):
        pad = {"padx": 20, "pady": (10, 0)}
        ...기존 _build_ui 본문 전체...
```
기존 본문에서 위젯 부모로 쓰인 `self`를 **모두 `root`로** 바꾼다 — `ctk.CTkLabel(self, …)`, `ctk.CTkEntry(self, …)`, `ctk.CTkOptionMenu(self, …)`, `ctk.CTkFrame(self, …)`, `ctk.CTkButton(self, …)`, `ctk.CTkProgressBar(self)`. `command=self.xxx`, `self.url_entry = …` 같은 **속성 참조는 그대로** 둔다. 확인: `_build_download_tab` 안에서 `grep -n "(self,\|(self)" ` 결과가 0이어야 한다.

(e) `choose_folder` 끝에 리스너 호출 추가:
```python
    def choose_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.save_dir)
        if chosen:
            self.save_dir = chosen
            self.folder_label.configure(text=chosen)
            # 마지막 사용 폴더 기억
            self.settings["last_dir"] = chosen
            save_settings(self.settings)
            for cb in self.folder_listeners:
                cb(chosen)
```

(f) `on_download_click` 첫 줄의 `if self.busy: return` 을 경고로 바꾼다:
```python
        if self.busy:
            messagebox.showinfo("안내", "다른 작업이 진행 중이에요. 끝난 뒤 다시 시도해 주세요.")
            return
```
(`on_shift_existing_click`의 같은 검사도 동일하게.)

(g) `main()` 위에 번들 캐시 설정과 selftest 추가:
```python
def configure_bundled_model_cache() -> None:
    """풀 exe 에 같이 넣은 Demucs 가중치(HuggingFace 캐시)를 쓰게 한다.
    demucs 를 import 하기 전에 호출해야 한다."""
    bundled = resource_path("hf_home")
    if getattr(sys, "frozen", False) and os.path.isdir(bundled):
        os.environ.setdefault("HF_HOME", bundled)
        os.environ.setdefault("HF_HUB_OFFLINE", "1")


def selftest() -> int:
    """GUI 없이 번들이 멀쩡한지 확인. CI 가 빌드 직후 exe 로 실행한다.
    0 = 정상. 라이트는 ffmpeg 만, 풀은 모델 로드까지 확인."""
    configure_bundled_model_cache()
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("selftest: ffmpeg not found", file=sys.stderr)
        return 1
    from stems_page import stems_available
    if stems_available():
        import demucs.api
        from separator import MODEL_NAME
        sep = demucs.api.Separator(model=MODEL_NAME, device="cpu")
        print(f"selftest: full build ok, stems={list(sep.sources)}")
    else:
        print("selftest: lite build ok")
    return 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    configure_bundled_model_cache()
    try:
        app = App()
        ...기존 그대로...
```

- [ ] **Step 5: 통과 확인**

```bash
.venv/bin/pytest tests/test_app_tabs.py tests/test_selftest.py -q
.venv/bin/python main.py --selftest
.venv/bin/python -m pyflakes main.py stems_page.py
```
Expected: 5 passed, selftest 출력 `selftest: full build ok, stems=['drums', 'bass', 'other', 'vocals', 'guitar', 'piano']`, pyflakes 무출력.
(풀 환경에서 `python main.py`로 GUI를 띄우면 `cannot import name 'StemsPage'`가 나는 게 이 시점엔 정상.)

- [ ] **Step 6: 라이트 환경 수동 확인**

demucs 없는 임시 venv로 앱을 띄워 스템 탭에 안내만 보이는지 확인:
```bash
/opt/homebrew/bin/python3.12 -m venv /tmp/lite-venv && /tmp/lite-venv/bin/pip install -q -r requirements.txt
/tmp/lite-venv/bin/python main.py --selftest     # → selftest: lite build ok
/tmp/lite-venv/bin/python main.py                # 창: 탭 2개, 스템 탭 = 안내 문구. 확인 후 닫기
```

- [ ] **Step 7: 커밋**

```bash
git add main.py stems_page.py tests/test_app_tabs.py tests/test_selftest.py
git commit -m "feat: tabbed UI (download / stems), lite placeholder, --selftest

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `StemsPage` — 스템 분리 탭 UI + 워커

**Files:**
- Modify: `stems_page.py` (`StemsPage` 클래스 추가, `make_stems_tab`의 임시 import 제거)
- Test: `tests/test_stems_page.py`, `tests/test_app_tabs.py`(기존 4개 전부 통과)

**Interfaces:**
- Consumes: `separator.STEM_LABELS/STEM_ORDER/DEFAULT_STEMS/separate/translate_stem_error`, `common.KEY_VALUES/KEY_HELP/parse_key/is_youtube_url/translate_error/collect_filepaths/open_path`, `App.busy/save_dir/ffmpeg_path/after/folder_listeners/choose_folder`
- Produces:
  - `StemsPage(parent, app)`; `selected_stems() -> list[str]`; `resolve_input() -> tuple[str, str] | None` (`("file", path)` / `("url", url)`); `on_start_click()`; `set_status(text)`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_stems_page.py`:
```python
import pytest

pytest.importorskip("demucs.api")

import stems_page  # noqa: E402
from separator import DEFAULT_STEMS  # noqa: E402


def _page():
    import main
    try:
        app = main.App()
    except Exception as e:
        pytest.skip(f"GUI를 만들 수 없음: {e}")
    app.update()
    assert isinstance(app.stems_page, stems_page.StemsPage)
    return app, app.stems_page


def test_default_stems_checked():
    app, page = _page()
    try:
        assert page.selected_stems() == DEFAULT_STEMS
    finally:
        app.destroy()


def test_resolve_input_prefers_file(tmp_path):
    app, page = _page()
    try:
        assert page.resolve_input() is None
        page.url_entry.insert(0, "https://youtu.be/abc")
        assert page.resolve_input() == ("url", "https://youtu.be/abc")
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        page.file_path = str(f)
        assert page.resolve_input() == ("file", str(f))
    finally:
        app.destroy()


def test_start_requires_stem(monkeypatch, tmp_path):
    app, page = _page()
    try:
        warned = []
        monkeypatch.setattr("stems_page.messagebox.showwarning", lambda *a: warned.append(a))
        started = []
        monkeypatch.setattr("stems_page.threading.Thread",
                            lambda **kw: started.append(kw) or _FakeThread())
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        page.file_path = str(f)
        for var in page.stem_vars.values():
            var.set(False)
        page.on_start_click()
        assert warned and started == [] and app.busy is False
    finally:
        app.destroy()


def test_start_blocked_when_busy(monkeypatch, tmp_path):
    app, page = _page()
    try:
        shown = []
        monkeypatch.setattr("stems_page.messagebox.showinfo", lambda *a: shown.append(a))
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        page.file_path = str(f)
        app.busy = True
        page.on_start_click()
        assert shown
    finally:
        app.destroy()


def test_folder_label_follows_app(monkeypatch, tmp_path):
    app, page = _page()
    try:
        monkeypatch.setattr("main.filedialog.askdirectory", lambda **kw: str(tmp_path))
        monkeypatch.setattr("main.save_settings", lambda s: None)
        app.choose_folder()
        assert page.folder_label.cget("text") == str(tmp_path)
    finally:
        app.destroy()


class _FakeThread:
    def start(self):
        pass
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_stems_page.py -q`
Expected: `ImportError: cannot import name 'StemsPage' from 'stems_page'`

- [ ] **Step 3: `stems_page.py`에 `StemsPage` 추가**

파일 상단 import를 이렇게 바꾼다:
```python
import os
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
import yt_dlp

from common import (
    KEY_VALUES, KEY_HELP, parse_key, is_youtube_url,
    translate_error, collect_filepaths, open_path,
)
```
`make_stems_tab` 안의 `from stems_page import StemsPage` 줄을 지우고(아래 최종 형태 참고), `LitePlaceholder` 아래에 추가:

```python
FORMAT_LABELS = ["WAV", "MP3 320kbps"]
FORMAT_TO_EXT = {"WAV": "wav", "MP3 320kbps": "mp3"}

AUDIO_FILETYPES = [("오디오 파일", "*.mp3 *.m4a *.wav *.opus *.webm *.ogg *.flac"),
                   ("모든 파일", "*.*")]


class StemsPage(ctk.CTkFrame):
    """스템 분리 탭. 입력(파일 or 링크) → separator.separate → 폴더에 저장."""

    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.pack(fill="both", expand=True)
        self.app = app
        self.file_path: str | None = None
        self.out_dir: str | None = None
        self._build()
        app.folder_listeners.append(lambda d: self.folder_label.configure(text=d))

    # ── UI ──
    def _build(self):
        from separator import STEM_LABELS, STEM_ORDER, DEFAULT_STEMS
        pad = {"padx": 20, "pady": (10, 0)}

        ctk.CTkLabel(self, text="🎛️ 스템 분리", font=ctk.CTkFont(size=22, weight="bold")).pack(**pad)
        ctk.CTkLabel(self, text="유튜브 링크 또는 음원 파일 (파일이 우선):", anchor="w").pack(fill="x", **pad)
        self.url_entry = ctk.CTkEntry(self, placeholder_text="https://www.youtube.com/watch?v=...")
        self.url_entry.pack(fill="x", padx=20, pady=(4, 0))

        file_row = ctk.CTkFrame(self, fg_color="transparent")
        file_row.pack(fill="x", padx=20, pady=(6, 0))
        ctk.CTkButton(file_row, text="🎵 파일 선택", width=110, command=self.on_choose_file).pack(side="left")
        ctk.CTkButton(file_row, text="✕", width=32, fg_color="gray30", hover_color="gray25",
                      command=self.on_clear_file).pack(side="left", padx=(6, 0))
        self.file_label = ctk.CTkLabel(file_row, text="(선택 안 함)", anchor="w",
                                       font=ctk.CTkFont(size=11), text_color="gray70")
        self.file_label.pack(side="left", padx=(10, 0), fill="x", expand=True)

        ctk.CTkLabel(self, text="저장할 스템:", anchor="w").pack(fill="x", **pad)
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=20, pady=(4, 0))
        self.stem_vars: dict[str, ctk.BooleanVar] = {}
        for i, name in enumerate(STEM_ORDER):
            var = ctk.BooleanVar(value=name in DEFAULT_STEMS)
            self.stem_vars[name] = var
            ctk.CTkCheckBox(grid, text=STEM_LABELS[name], variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 16), pady=2)
        ctk.CTkLabel(
            self, text="기타·건반 분리는 보컬·드럼보다 품질이 낮을 수 있어요.",
            justify="left", anchor="w", font=ctk.CTkFont(size=11), text_color="gray70",
        ).pack(fill="x", padx=20, pady=(4, 0))

        opt_row = ctk.CTkFrame(self, fg_color="transparent")
        opt_row.pack(fill="x", padx=20, pady=(10, 0))
        ctk.CTkLabel(opt_row, text="출력 포맷:").pack(side="left")
        self.format_menu = ctk.CTkOptionMenu(opt_row, values=FORMAT_LABELS, width=130)
        self.format_menu.set(FORMAT_LABELS[0])
        self.format_menu.pack(side="left", padx=(8, 20))
        ctk.CTkLabel(opt_row, text="키 조정 (반음):").pack(side="left")
        self.key_menu = ctk.CTkOptionMenu(opt_row, values=KEY_VALUES, width=110)
        self.key_menu.set("0 (원본)")
        self.key_menu.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(self, text=KEY_HELP, justify="left", anchor="w",
                     font=ctk.CTkFont(size=11), text_color="gray70").pack(fill="x", padx=20, pady=(4, 0))

        folder_row = ctk.CTkFrame(self, fg_color="transparent")
        folder_row.pack(fill="x", padx=20, pady=(10, 0))
        ctk.CTkButton(folder_row, text="📁 저장 폴더 선택", width=130,
                      command=self.app.choose_folder).pack(side="left")
        self.folder_label = ctk.CTkLabel(folder_row, text=self.app.save_dir, anchor="w",
                                         font=ctk.CTkFont(size=11), text_color="gray70")
        self.folder_label.pack(side="left", padx=(10, 0), fill="x", expand=True)

        self.start_btn = ctk.CTkButton(self, text="🎛️ 분리 시작", height=40,
                                       font=ctk.CTkFont(size=16, weight="bold"),
                                       command=self.on_start_click)
        self.start_btn.pack(fill="x", padx=20, pady=(14, 0))

        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=20, pady=(14, 0))
        self.status_label = ctk.CTkLabel(self, text="대기 중", anchor="w")
        self.status_label.pack(fill="x", padx=20, pady=(6, 0))

        self.open_btn = ctk.CTkButton(self, text="📂 결과 폴더 열기", command=self.open_result,
                                      fg_color="gray30", hover_color="gray25", state="disabled")
        self.open_btn.pack(fill="x", padx=20, pady=(10, 16))

    # ── 유틸 ──
    def set_status(self, text: str):
        self.status_label.configure(text=text)

    def selected_stems(self) -> list[str]:
        from separator import STEM_ORDER
        return [n for n in STEM_ORDER if self.stem_vars[n].get()]

    def resolve_input(self):
        """("file", 경로) / ("url", 링크) / None. 파일이 링크보다 우선."""
        if self.file_path:
            return ("file", self.file_path)
        url = self.url_entry.get().strip()
        if url:
            return ("url", url)
        return None

    def on_choose_file(self):
        chosen = filedialog.askopenfilename(title="분리할 음원 파일 선택", filetypes=AUDIO_FILETYPES)
        if chosen:
            self.file_path = chosen
            self.file_label.configure(text=os.path.basename(chosen))

    def on_clear_file(self):
        self.file_path = None
        self.file_label.configure(text="(선택 안 함)")

    def open_result(self):
        open_path(self.out_dir or self.app.save_dir)

    # ── 시작 ──
    def on_start_click(self):
        if self.app.busy:
            messagebox.showinfo("안내", "다른 작업이 진행 중이에요. 끝난 뒤 다시 시도해 주세요.")
            return
        src = self.resolve_input()
        if src is None:
            messagebox.showwarning("안내", "유튜브 링크를 붙여넣거나 음원 파일을 선택해 주세요!")
            return
        if src[0] == "url" and not is_youtube_url(src[1]):
            messagebox.showwarning("안내", "유튜브 링크가 아닌 것 같아요.\n"
                                   "youtube.com 또는 youtu.be 로 시작하는 주소를 넣어 주세요.")
            return
        stems = self.selected_stems()
        if not stems:
            messagebox.showwarning("안내", "저장할 스템을 하나 이상 체크해 주세요.")
            return
        if not self.app.ffmpeg_path:
            messagebox.showerror("FFmpeg 없음",
                                 "스템 분리에는 FFmpeg가 필요한데 찾지 못했습니다.\n"
                                 "ffmpeg.exe 를 이 프로그램과 같은 폴더에 넣어 주세요. (README 참고)")
            return

        fmt = FORMAT_TO_EXT[self.format_menu.get()]
        semitones = parse_key(self.key_menu.get())

        self.app.busy = True
        self.start_btn.configure(state="disabled", text="분리 중...")
        self.open_btn.configure(state="disabled")
        self.progress.set(0)
        self.set_status("준비 중...")
        threading.Thread(
            target=self._worker, args=(src, stems, fmt, semitones), daemon=True,
        ).start()

    # ── 워커 (별도 스레드) ──
    def _worker(self, src, stems, fmt, semitones):
        stage = "download"
        try:
            kind, value = src
            input_path = self._download(value) if kind == "url" else value
            stage = "separate"
            from separator import separate, translate_stem_error  # 지연 import (torch 로딩)
            out_dir = os.path.join(self.app.save_dir, f"{Path(input_path).stem}_stems")
            saved = separate(
                input_path, stems, out_dir, fmt, self.app.ffmpeg_path, semitones,
                on_progress=lambda frac, text: self.app.after(
                    0, lambda: (self.progress.set(frac), self.set_status(text))),
            )
            self.app.after(0, lambda: self._on_done(out_dir, saved))
        except Exception as e:
            if stage == "separate":
                from separator import translate_stem_error
                msg = translate_stem_error(e)
            else:
                msg = translate_error(e)
            self.app.after(0, lambda: self._on_error(msg))

    def _download(self, url: str) -> str:
        """링크를 m4a 로 받아 경로를 돌려준다 (다운로드 탭과 같은 옵션, 재생목록은 첫 곡만)."""
        ydl_opts = {
            "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": os.path.join(self.app.save_dir, "%(title)s.%(ext)s"),
            "windowsfilenames": True,
            "noplaylist": True,
            "progress_hooks": [self._progress_hook],
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "retries": 3,
        }
        if self.app.ffmpeg_path:
            ydl_opts["ffmpeg_location"] = self.app.ffmpeg_path
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        paths = collect_filepaths(info)
        if not paths:
            raise RuntimeError("다운로드한 파일을 찾지 못했습니다.")
        return paths[0]

    def _progress_hook(self, d: dict):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            frac = (done / total) if total else 0
            text = f"다운로드 중... {frac * 100:.1f}%"
            self.app.after(0, lambda: (self.progress.set(frac * 0.3), self.set_status(text)))

    # ── 완료 / 실패 (메인 스레드) ──
    def _on_done(self, out_dir: str, saved: list[str]):
        self.app.busy = False
        self.out_dir = out_dir
        self.start_btn.configure(state="normal", text="🎛️ 분리 시작")
        self.open_btn.configure(state="normal")
        self.progress.set(1.0)
        self.set_status(f"✅ 완료: {len(saved)}개 스템 저장")
        names = "\n".join(os.path.basename(p) for p in saved)
        messagebox.showinfo("완료", f"스템 분리가 끝났습니다! 🎛️\n\n{names}\n\n폴더:\n{out_dir}")

    def _on_error(self, korean_msg: str):
        self.app.busy = False
        self.start_btn.configure(state="normal", text="🎛️ 분리 시작")
        self.progress.set(0)
        self.set_status("❌ 실패 — 아래 안내를 확인하세요.")
        messagebox.showerror("스템 분리 실패", korean_msg)
```
`make_stems_tab`는 최종적으로:
```python
def make_stems_tab(parent, app) -> ctk.CTkFrame:
    if not stems_available():
        return LitePlaceholder(parent)
    return StemsPage(parent, app)
```
(`StemsPage`가 아래에 정의돼도 호출 시점엔 존재하므로 순서 무관.)

- [ ] **Step 4: 통과 확인**

```bash
.venv/bin/pytest tests/ -q
.venv/bin/python -m pyflakes main.py common.py stems_page.py separator.py
```
Expected: 전부 통과 (test_separator는 모델 실행으로 1분 안팎), pyflakes 무출력.

- [ ] **Step 5: 수동 E2E (맥, 풀 환경)**

`.venv/bin/python main.py` → 스템 분리 탭:
1. 짧은 음원 파일(30초~1분)을 선택, 기본 5스템, WAV → 분리 시작. 진행바가 움직이고 완료 팝업, `<이름>_stems/` 에 5개 파일.
2. 같은 파일, 스템 `보컬`만, MP3 + 키 +2 → `보컬 (키+2).mp3` 1개. `.tmp.wav` 없음.
3. 유튜브 링크 하나 → 다운로드 후 분리까지 이어지는지.
4. 분리 중에 다운로드 탭에서 다운로드 클릭 → "다른 작업이 진행 중" 안내.
결과(걸린 시간 포함)를 보고한다. 창 크기 `560x780`에서 위젯이 잘리면 `App.geometry` 높이를 늘린다.

- [ ] **Step 6: 커밋**

```bash
git add stems_page.py tests/test_stems_page.py
git commit -m "feat: stem separation tab (file or YouTube link, stem checkboxes, key shift)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: CI 두 빌드(lite / full) + README

**Files:**
- Modify: `.github/workflows/build-windows.yml`
- Modify: `README.md`

**Interfaces:**
- Consumes: `main.py --selftest` (exit 0), `requirements-stems.txt`, `separator.MODEL_NAME`

- [ ] **Step 1: 워크플로 전체 교체**

`.github/workflows/build-windows.yml`:
```yaml
name: Build Windows EXE

# main.py 를 윈도우 러너에서 PyInstaller 로 빌드한다.
#  - lite: 다운로드만. 단일 exe (ffmpeg 번들)
#  - full: 스템 분리 포함. torch 가 커서 onedir 폴더를 zip 으로 (모델 가중치 hf_home 포함)
# 맥에서는 gh run download 로 내려받으면 된다.

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  build-lite:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt pyinstaller

      - name: Download ffmpeg (static build)
        shell: pwsh
        run: |
          $url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
          Invoke-WebRequest -Uri $url -OutFile ffmpeg.zip
          Expand-Archive -Path ffmpeg.zip -DestinationPath ffmpeg_tmp -Force
          $exe = Get-ChildItem -Path ffmpeg_tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
          Copy-Item $exe.FullName -Destination ffmpeg.exe

      - name: Build EXE (PyInstaller, onefile)
        shell: pwsh
        run: |
          pyinstaller --onefile --noconsole `
            --name "youtube-audio-downloader" `
            --collect-all customtkinter `
            --add-binary "ffmpeg.exe;." `
            main.py

      - name: Selftest built exe
        shell: pwsh
        run: |
          & .\dist\youtube-audio-downloader.exe --selftest
          if ($LASTEXITCODE -ne 0) { throw "selftest failed ($LASTEXITCODE)" }

      - uses: actions/upload-artifact@v4
        with:
          name: youtube-audio-downloader-lite-exe
          path: dist/youtube-audio-downloader.exe
          if-no-files-found: error

  build-full:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies (with demucs + torch CPU)
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-stems.txt pyinstaller

      - name: Download ffmpeg (static build)
        shell: pwsh
        run: |
          $url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
          Invoke-WebRequest -Uri $url -OutFile ffmpeg.zip
          Expand-Archive -Path ffmpeg.zip -DestinationPath ffmpeg_tmp -Force
          $exe = Get-ChildItem -Path ffmpeg_tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
          Copy-Item $exe.FullName -Destination ffmpeg.exe

      - name: Prefetch Demucs weights into hf_home
        shell: pwsh
        env:
          HF_HOME: ${{ github.workspace }}\hf_home
          HF_HUB_DISABLE_SYMLINKS_WARNING: "1"
        run: |
          python -c "import demucs.api; from separator import MODEL_NAME; s = demucs.api.Separator(model=MODEL_NAME, device='cpu'); print('sources', s.sources)"
          Get-ChildItem -Recurse hf_home | Measure-Object -Property Length -Sum | Select-Object Sum

      - name: Build (PyInstaller, onedir)
        shell: pwsh
        run: |
          pyinstaller --onedir --noconsole `
            --name "youtube-audio-downloader-full" `
            --collect-all customtkinter `
            --collect-all demucs `
            --add-binary "ffmpeg.exe;." `
            --add-data "hf_home;hf_home" `
            main.py

      - name: Selftest built exe (offline, bundled weights)
        # HF_HOME 을 여기서 지정하면 안 된다 — exe 안의 configure_bundled_model_cache 가
        # setdefault 로 번들 경로를 넣으므로, 비워 둬야 번들 가중치로 로드되는지 검증된다.
        # (러너 기본 캐시는 비어 있다: 앞 단계가 HF_HOME 을 hf_home 으로 바꿔 받았기 때문)
        shell: pwsh
        env:
          HF_HUB_OFFLINE: "1"
        run: |
          & .\dist\youtube-audio-downloader-full\youtube-audio-downloader-full.exe --selftest
          if ($LASTEXITCODE -ne 0) { throw "selftest failed ($LASTEXITCODE)" }

      - name: Zip
        shell: pwsh
        run: Compress-Archive -Path dist\youtube-audio-downloader-full -DestinationPath youtube-audio-downloader-full.zip

      - uses: actions/upload-artifact@v4
        with:
          name: youtube-audio-downloader-full-zip
          path: youtube-audio-downloader-full.zip
          if-no-files-found: error
```
- [ ] **Step 2: yaml 문법 확인**

```bash
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/build-windows.yml')); print('yaml ok')"
```
(`yaml`은 demucs 의존성으로 이미 설치돼 있다.)

- [ ] **Step 3: README 갱신**

`## 1. 개발 환경 설치` 절의 코드블록 아래에 추가:
```markdown
### 라이트 / 풀 버전

| | 라이트 | 풀 |
|---|---|---|
| 기능 | 다운로드 + 키 조정 | 라이트 + **스템 분리** (보컬·드럼·기타·건반·베이스·그외) |
| 배포 | `youtube-audio-downloader.exe` 하나 | `youtube-audio-downloader-full.zip` (풀어서 폴더 안의 exe 실행) |
| 용량 | 수십 MB | 수백 MB (PyTorch + Demucs 모델 포함) |

소스로 풀 버전을 쓰려면:
```bash
pip install -r requirements-stems.txt
python main.py
```
- 스템 분리는 CPU로 돌아가요. 3~4분 곡 기준 **수 분** 걸립니다.
- 소스 실행 시 첫 분리 때 모델(약 80MB)을 자동으로 받아요. zip 배포본은 이미 들어 있어요.
- 기타·건반 분리 품질은 보컬·드럼보다 낮은 편이에요 (모델 한계).
- 테스트: `pip install -r requirements-dev.txt && pytest`
```

`## 3. 단일 .exe로 빌드하기` 절 끝에 추가:
```markdown
### 풀 버전(스템 분리) 빌드

GitHub Actions의 `build-full` 잡이 자동으로 만듭니다 (Actions 탭 → 아티팩트 `youtube-audio-downloader-full-zip`).
직접 빌드하려면 `.github/workflows/build-windows.yml`의 `build-full` 단계를 그대로 따라 하세요 — 핵심은
모델 가중치를 `hf_home/`에 미리 받아 `--add-data "hf_home;hf_home"`으로 넣고, `--onedir`로 빌드하는 것입니다.
빌드 결과가 멀쩡한지는 `exe --selftest` 로 확인할 수 있어요 (종료 코드 0이면 정상).
```

`## 4. 사용법 (친구용)` 절 끝에 추가:
```markdown
### 스템 분리 (풀 버전)

1. `스템 분리` 탭 → 유튜브 링크를 붙여넣거나 `파일 선택`으로 음원 파일 선택 (둘 다 있으면 파일 우선)
2. 저장할 스템 체크 (기본: 보컬·드럼·기타·건반·베이스)
3. 출력 포맷(WAV/MP3)·키 조정 선택 → `분리 시작`
4. 저장 폴더 안에 `<곡이름>_stems/` 폴더가 생기고 `보컬.wav`, `드럼.wav` … 가 들어 있어요.
```

- [ ] **Step 4: 커밋**

```bash
git add .github/workflows/build-windows.yml README.md
git commit -m "ci: build lite (onefile) and full (onedir + bundled Demucs weights) variants; docs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 5: 사용자에게 push 요청**

push는 사용자가 한다. push 후 Actions에서 두 잡이 초록인지, `build-full`의 selftest 단계 로그에 `selftest: full build ok, stems=[...]`가 찍혔는지 확인. PyInstaller가 torch/sphn/lameenc 모듈을 못 찾아 selftest가 실패하면 해당 모듈에 `--collect-all <모듈>`을 추가해 재시도 (한 번에 하나씩, 커밋 메시지에 어떤 모듈이었는지 기록).

---

## 자체 검토 결과

- **스펙 커버리지:** 파일 구조·common 이동(T1), separator 인터페이스·ffmpeg 디코드·mp3/키조정·진행률·에러 문구(T2), 탭·라이트 안내·busy 공유·폴더 공유·selftest·번들 캐시 env(T3), StemsPage 위젯·입력 우선순위·재생목록 첫 곡·출력 폴더명(T4), CI 두 잡·가중치 번들·zip·README·gitignore(T0/T5). 스펙의 "상대 탭 버튼 비활성"은 확인 절에 따라 busy 검사 + 안내로 대체.
- **타입 일관성:** `separate(input_path, stems, out_dir, fmt, ffmpeg, semitones, on_progress)` 시그니처가 T2 정의·T4 호출·테스트에서 동일. `App.busy`, `folder_listeners`, `stems_page`, `tabview` 이름이 T3 정의·T4 사용·테스트에서 동일. `STEM_ORDER`/`DEFAULT_STEMS`/`STEM_LABELS` 동일.
- **Review Focus 5개** 모두 테스트에 매핑됨 (T2: m4a·mp3+키, T3: 라이트, T4: 입력 우선순위·스템 미선택).
- **알려진 불확실성:** (1) PyInstaller가 torch를 onedir로 묶을 때 hidden import 누락 가능 — T5 Step 5의 selftest가 잡는다. (2) demucs 콜백의 `segment_offset`가 패딩 때문에 `audio_length`를 넘을 수 있음 — `min(…,1.0)`으로 clamp. (3) `htdemucs_6s` 첫 다운로드가 HF Hub 속도에 좌우됨.
