# 스템 분리 기능 설계 (2026-09-24)

## 목표

유튜브 오디오 다운로더에 **스템 분리** 페이지를 추가한다. 곡을 보컬·드럼·기타·건반·베이스(+other)로 나눠 저장한다.
배포는 **두 버전**으로 나눈다:

| 버전 | 내용 | 배포 형태 |
|---|---|---|
| **라이트** | 다운로드만 (지금과 동일) | 단일 exe, 수십 MB |
| **풀** | 다운로드 + 스템 분리 | 폴더째 zip, 수백 MB (PyTorch 포함) |

코드는 하나(`main.py` 계열)이고, 빌드와 의존성 파일만 둘로 나눈다.

## 사용자가 확정한 요구사항

- 분리 엔진: **Demucs 내장**, 모델 `htdemucs_6s` (6스템: vocals, drums, bass, guitar, piano, other)
- 저장할 스템: 체크박스 6개. **보컬·드럼·기타·건반·베이스 기본 체크**, other는 기본 해제
- 입력: **로컬 파일 + 유튜브 링크** 둘 다
- 화면: 페이지(탭) 2개 — `다운로드` / `스템 분리`
- 라이트/풀 두 버전

## 설계자가 정한 것 (사용자 승인됨)

- 스템 출력 포맷: **WAV / MP3 320kbps** 중 선택 (m4a·원본 옵션 없음)
- 스템 탭에도 **키 조정** 있음 — 기존 `pitch_filter`를 스템마다 적용
- 풀 버전은 PyInstaller `--onedir` + zip (torch가 든 onefile은 시작이 10초 이상 걸림)
- 모델 가중치는 CI에서 미리 받아 풀 버전 zip에 포함 (첫 실행 때 다운로드 대기 없음)
- 라이트 버전에서도 스템 탭은 보이되 "풀 버전에서 지원돼요" 안내만 표시

## 아키텍처

### 파일 구조

```
main.py          진입점. App(CTk) = 탭 호스트 + 다운로드 탭(기존 로직 그대로)
common.py        main.py에서 옮긴 UI 무관 헬퍼 (아래 목록)
stems_page.py    스템 분리 탭 UI (CTkFrame 서브클래스). demucs 없으면 안내 프레임
separator.py     Demucs 호출. UI 의존 없음. 단독 테스트 가능
requirements.txt        라이트: yt-dlp, customtkinter
requirements-stems.txt  풀: -r requirements.txt + demucs + torch(CPU) + torchaudio(CPU)
.github/workflows/build-windows.yml   잡 2개: build-lite, build-full
```

**`common.py`로 옮기는 것** (내용 수정 없이 이동만): `resource_path`, `app_dir`, `find_ffmpeg`, `KEY_VALUES`, `KEY_HELP`, `parse_key`, `pitch_filter`, `CODEC_BY_EXT`, `shift_pitch`, `is_youtube_url`, `translate_error`. `main.py`는 `from common import …`로 바꾼다.
`stems_page.py`와 `separator.py`는 `common`만 import하고 `main`은 import하지 않는다 — `python main.py`로 실행하면 main이 `__main__` 모듈이라, 다른 파일에서 `import main`을 하면 같은 코드가 두 번 로드되기 때문.
`main.py`는 `stems_page`를 `App.__init__` 안에서 지연 import한다 (라이트 버전은 stems_page의 안내 프레임만 씀).
`demucs`/`torch`를 모듈 최상단에서 import하는 파일은 `separator.py` 하나뿐이고, `stems_page.py`는 `separator`를 워커 스레드 안에서 지연 import한다 — 라이트 환경에서도 `stems_page`가 문제없이 로드돼야 하기 때문.

`.gitignore`에 `torch_home/`, `.DS_Store` 추가.

### 기능 감지 (라이트 / 풀 판별)

```python
# main.py
def stems_available() -> bool:
    try:
        import demucs.api  # noqa
        return True
    except ImportError:
        return False
```

풀 여부는 이 함수 하나로만 판단한다. 별도 플래그·환경변수 없음.

### 화면

`App.__init__`에서 `CTkTabview` 생성, 탭 `"다운로드"`, `"스템 분리"`.
- 창 크기: 기존 `560x700` → 탭 헤더만큼 높이 여유 (`560x760` 정도, 구현 시 조정).
- `다운로드` 탭: 기존 `_build_ui`의 위젯들을 `self` 대신 탭 프레임에 붙인다. 로직 변경 없음.
- `스템 분리` 탭: `stems_available()`이면 `StemsPage(tab, app)`, 아니면 안내 라벨 + README 링크 문구.

`StemsPage` 위젯 (위→아래):
1. 유튜브 링크 입력칸 (`CTkEntry`)
2. `파일 선택` 버튼 + 선택한 파일명 라벨 — 파일을 고르면 링크 칸은 무시, 링크 칸에 값이 있으면 파일 선택 무시. 둘 다 있으면 **파일 우선**, 둘 다 없으면 경고.
3. 스템 체크박스 6개 (2열): 보컬 · 드럼 · 기타 · 건반 · 베이스 · 그 외(other). 앞 5개 기본 체크.
4. 출력 포맷 `CTkOptionMenu`: `WAV` / `MP3 320kbps`
5. 키 조정 `CTkOptionMenu`: 기존 `KEY_VALUES` 재사용
6. 저장 폴더 버튼 + 라벨: 다운로드 탭과 **같은** `app.save_dir` 공유
7. `분리 시작` 버튼 (진행 중엔 비활성 + "분리 중...")
8. `CTkProgressBar` + 상태 라벨 + `폴더 열기` 버튼

### 분리 흐름 (`StemsPage._run_worker`, 별도 스레드)

```
입력 결정
  ├ 파일 → 그 경로
  └ 링크 → yt-dlp로 m4a(bestaudio[ext=m4a]) 다운로드. main.py의 ydl_opts 구성을 재사용.
           저장 위치: app.save_dir. 재생목록은 첫 영상만 (noplaylist=True, 묻지 않음)
        ↓
separator.separate(input_path, stems=[...], out_dir, fmt, ffmpeg, semitones, on_progress)
        ↓
완료 → 상태 "완료: N개 스템 저장" + 폴더 열기 버튼 활성화
```

출력 폴더: `<app.save_dir>/<입력파일 stem>_stems/`. 파일명은 한국어 라벨:
`보컬.wav`, `드럼.wav`, `기타.wav`, `건반.wav`, `베이스.wav`, `그외.wav`.
키 조정 시 `보컬 (키+2).wav` 형태 (기존 `shift_pitch` 명명 규칙과 동일).

### `separator.py` 인터페이스

```python
STEM_LABELS = {          # demucs 이름 → 한국어 파일명
    "vocals": "보컬", "drums": "드럼", "guitar": "기타",
    "piano": "건반", "bass": "베이스", "other": "그외",
}
DEFAULT_STEMS = ["vocals", "drums", "guitar", "piano", "bass"]

def separate(
    input_path: str,
    stems: list[str],            # demucs 이름
    out_dir: str,                # 없으면 separate가 만든다 (os.makedirs)
    fmt: str,                    # "wav" | "mp3"
    ffmpeg: str | None,          # mp3·키조정에 필요
    semitones: int = 0,
    on_progress: Callable[[float, str], None] | None = None,  # (0.0~1.0, 상태문구)
) -> list[str]:                  # 저장된 파일 경로들
```

내부:
- `demucs.api.Separator(model="htdemucs_6s", device="cpu", progress=False, callback=cb)`
- `origin, sources = sep.separate_audio_file(input_path)` — `sources`는 `{stem: Tensor}`
- 콜백은 `info["segment_offset"] / info["audio_length"]`로 진행률 계산 → `on_progress(frac, "분리 중 …%")`
- 저장: `demucs.api.save_audio(tensor, path, samplerate=sep.samplerate)` — WAV로 저장한 뒤,
  - fmt가 mp3면 ffmpeg로 `libmp3lame -b:a 320k` 변환 후 wav 삭제
  - semitones≠0이면 `main.shift_pitch`와 같은 필터 체인으로 변환 (wav→wav 또는 wav→mp3 한 번에)
- 모델 로딩 전 `on_progress(0, "모델 불러오는 중…")`. 첫 실행이고 가중치가 없으면 demucs가 자동 다운로드하므로 문구를 "모델 다운로드 중… (최초 1회)"로.

### 모델 가중치 위치

demucs는 `torch.hub` 캐시(`$TORCH_HOME/hub/checkpoints/`)에서 가중치를 찾고 없으면 받는다.
- 풀 exe: 빌드 시 `torch_home/hub/checkpoints/<htdemucs_6s 가중치>.th`를 `--add-data`로 포함. `main.py` 시작부에서 `sys.frozen`이고 `resource_path("torch_home")`이 있으면 `os.environ.setdefault("TORCH_HOME", …)` — **demucs/torch import 전에** 설정.
- 소스 실행(맥 등): 기본 캐시 사용, 최초 1회 자동 다운로드.

### 스레드·에러 처리

- 기존 패턴 그대로: 워커 스레드 → `app.after(0, …)`로 UI 갱신.
- 다운로드 탭과 스템 탭이 **동시에 돌지 않게** `app.busy` 플래그 하나를 공유. 한쪽이 돌면 다른 쪽 시작 버튼 비활성.
- 예외는 `translate_error`를 거쳐 `messagebox.showerror`. 스템 전용 메시지 추가:
  - 메모리 부족(`RuntimeError`에 "out of memory") → "메모리가 부족해요. 더 짧은 곡으로 시도하거나 다른 프로그램을 닫아 주세요."
  - 지원 안 되는 입력 파일 → "읽을 수 없는 오디오 파일이에요. mp3·wav·m4a·flac을 넣어 주세요."
- mp3 출력 또는 키 조정인데 ffmpeg 없음 → 시작 전에 차단 (다운로드 탭과 같은 안내).

## 빌드·배포

### `requirements-stems.txt`

```
-r requirements.txt
--extra-index-url https://download.pytorch.org/whl/cpu
torch
torchaudio
demucs
```

CPU 전용 휠을 써서 CUDA 수 GB를 피한다. 정확한 버전 핀은 구현 시 CI에서 통과하는 조합으로 고정한다.

### CI (`build-windows.yml`)

잡 두 개, 둘 다 `windows-latest`, ffmpeg 다운로드 단계는 공통:

- **build-lite**: 지금 잡 그대로. 산출물 `youtube-audio-downloader.exe`
- **build-full**:
  1. `pip install -r requirements-stems.txt pyinstaller`
  2. `python -c "import demucs.api; demucs.api.Separator(model='htdemucs_6s')"` 로 가중치를 캐시에 받은 뒤 `torch_home/hub/checkpoints/`로 복사
  3. `pyinstaller --onedir --noconsole --name youtube-audio-downloader-full --collect-all customtkinter --collect-all demucs --add-binary ffmpeg.exe;. --add-data torch_home;torch_home main.py`
     (torch 관련 hidden-import/`--collect-*`는 구현 중 빌드가 깨지는 지점에서 추가)
  4. `dist/youtube-audio-downloader-full/`를 zip → 아티팩트 `youtube-audio-downloader-full.zip`

### README

"라이트 / 풀 차이", 풀 버전 zip 푸는 법, 맥에서 소스 실행 시 `pip install -r requirements-stems.txt`, 첫 분리 때 모델 자동 다운로드 안내, 분리 속도(CPU, 3분 곡 기준 수 분) 항목을 추가한다.

## 검증

1. **`separator.py` 단위 테스트** (`tests/test_separator.py`, pytest): 5초짜리 합성 wav를 만들어 `separate(…, stems=["vocals","drums"], fmt="wav")` → 파일 2개 존재, 길이 ≈ 5초. demucs 미설치 환경에선 skip.
2. **라이트 모드 수동 확인**: `demucs` 없는 venv에서 `python main.py` → 스템 탭에 안내 문구만, 다운로드 탭 정상.
3. **풀 모드 수동 확인**: 실제 곡 하나 → 5개 스템 저장, 키 +2 + MP3 조합 1회.
4. **CI**: 두 잡 모두 초록. 풀 zip을 윈도우에서 풀어 실행, 스템 탭 동작 확인 (사용자가 수행).

## 범위 밖

- GPU 지원
- 스템 미리듣기·믹서
- 재생목록 일괄 분리
- 스템 탭에서 재생목록 전체 받기
