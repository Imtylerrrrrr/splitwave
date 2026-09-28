# 곡 보관함 설계

작성 2026-09-28. 브랜치 `library` (기반: main, v1.1.0). 릴리스 목표 v1.2.0 (허브 업데이트 테스트를 겸한다).

## 목적 (사용자 요청)

받아 둔 음원을 스템 분리와 템포 추종에서 **목록으로 보고 고를 수 있게** 한다.
다운로드에서는 고르는 것보다 **이미 받았는지** 알려 주는 정도면 된다.

합주 흐름: 곡을 받는다 → 스템으로 나눈다 → 빠진 악기 스템을 템포 추종으로 튼다.
지금은 단계마다 파일 선택 창에서 파일을 찾아야 한다. 이걸 없앤다.

## 결정

1. **보관함은 폴더다.** 저장 폴더 아래에 `Splitwave` 폴더를 만들고 거기에 받는다. 목록은 그 폴더를 읽어서 만든다.
   - 별도 데이터베이스가 없으므로 사용자가 파일을 직접 넣거나 지워도 목록이 맞는다.
   - 저장 폴더 전체(예: 다운로드 폴더)를 읽지 않으므로 관계없는 파일이 목록에 섞이지 않는다.
2. **세 앱이 같은 설정을 읽는다.** 기존 설정 파일(`%APPDATA%\yt_audio_downloader_config.json`)의 `last_dir` 가 저장 폴더다.
   템포 추종은 별도 실행파일이지만 같은 파일을 읽어 같은 보관함을 본다.
3. **"이미 받았는지"는 작은 색인 파일로 판단한다.** 유튜브 영상 ID → 받은 파일 이름. 목록 자체는 색인에 의존하지 않는다.
4. 고르는 화면은 드롭다운이다. 창 크기가 고정이라 목록 상자보다 자리를 덜 차지한다.

범위 밖: 곡 삭제·이름 변경 화면, 예전 폴더의 파일 자동 이동, 여러 스템 동시 재생, 검색.

## 폴더 구조

```
<저장 폴더>/Splitwave/                 보관함
    곡 제목.m4a                        받은 곡
    곡 제목 (키+2).m4a                 키 조정본 (기존 이름 규칙 그대로)
    곡 제목_stems/                     스템 분리 결과 (기존 이름 규칙 그대로)
        보컬.wav  드럼.wav  건반.wav ...
    .splitwave-index.json              색인 (영상 ID → 파일 이름)
```

- 저장 폴더의 이름이 이미 `Splitwave`(대소문자 무시)면 그 폴더를 보관함으로 쓴다 (`Splitwave/Splitwave` 를 만들지 않는다).
- 보관함 폴더는 처음 저장할 때 만든다. 목록을 읽을 때는 만들지 않는다 (없으면 빈 목록).

## `library.py` (새 모듈, 표준 라이브러리만, GUI·yt_dlp import 금지)

```python
LIBRARY_DIRNAME = "Splitwave"
INDEX_NAME = ".splitwave-index.json"
STEMS_SUFFIX = "_stems"
AUDIO_EXTS = (".m4a", ".mp3", ".wav", ".flac", ".ogg", ".opus", ".webm", ".aac", ".mka", ".mp4")

# 설정 (main.py 에서 옮겨 온다. main.py 는 여기서 import 해서 같은 이름으로 계속 쓴다)
def config_path() -> Path
def load_settings() -> dict
def save_settings(settings: dict) -> None
def default_download_dir() -> str

def base_dir(settings: dict | None = None) -> str   # settings 가 None 이면 load_settings(). last_dir 가 폴더면 그것, 아니면 default_download_dir()
def library_dir(base: str) -> str                   # 위 "폴더 구조" 규칙. 만들지 않는다
def ensure_library(base: str) -> str                # library_dir + os.makedirs(exist_ok=True)

@dataclass(frozen=True)
class Track:
    label: str          # 화면 이름: "곡 제목" 또는 "곡 제목 / 건반"
    path: str           # 절대 경로
    song: str           # 곡 이름 (확장자 뺀 파일 이름, 스템이면 폴더 이름에서 _stems 를 뺀 것)
    stem: str | None    # 스템 이름 (확장자 뺀 파일 이름). 곡 자체면 None

def list_songs(lib: str) -> list[Track]
def list_tracks(lib: str) -> list[Track]
def menu_labels(tracks: list[Track], max_len: int = 48) -> dict[str, str]

def video_id(url: str) -> str | None
def downloads_from_info(info: dict) -> list[tuple[str, list[str]]]
def record_download(lib: str, vid: str, paths: list[str]) -> None
def find_downloaded(lib: str, vid: str) -> list[str]
```

### 목록 규칙

- `list_songs`: 보관함 **바로 아래**의 파일 중 확장자(소문자 비교)가 `AUDIO_EXTS` 인 것. 이름이 `.` 으로 시작하면 제외.
  수정 시각 최신순, 같으면 이름순. 폴더가 없거나 읽을 수 없으면 빈 목록.
- `list_tracks`: 곡 단위로 묶는다. 묶음 = 곡 파일(있으면) + `<곡 이름>_stems/` 바로 아래의 오디오 파일(이름순).
  곡 파일 없이 스템 폴더만 있어도 묶음이 된다. 묶음 안 순서는 곡 먼저, 그다음 스템.
  묶음 순서는 묶음 안 파일의 수정 시각 중 가장 최근 것 기준 최신순, 같으면 곡 이름순.
  스템 폴더 안에 오디오 파일이 없으면 그 폴더는 무시한다.
- 스템의 `label` 은 `"<곡 이름> / <스템 이름>"`.
- `menu_labels`: 입력 순서를 지킨 `{표시 이름: 경로}`. 표시 이름이 `max_len` 보다 길면 끝을 `...` 로 줄인다 (줄인 뒤 길이가 `max_len`).
  스템 라벨은 곡 이름 쪽을 줄여 ` / <스템 이름>` 이 항상 보이게 한다. 표시 이름이 겹치면 두 번째부터 ` (2)`, ` (3)` 을 붙인다.

### 색인 규칙

- 파일: `<보관함>/.splitwave-index.json`, 내용 `{"version": 1, "videos": {"<영상 ID>": ["파일 이름", ...]}}`. 파일 이름은 보관함 기준 상대 경로(`/` 구분).
- 읽기 실패(없음, 깨짐, 형식 다름)는 빈 색인으로 취급한다. 쓰기는 임시 파일 + `os.replace`.
- `record_download`: 보관함 안의 경로만 기록한다 (밖이면 무시). 같은 이름은 한 번만. 쓰기 실패는 무시한다 (색인은 편의 기능이라 다운로드를 실패시키지 않는다).
- `find_downloaded`: 색인에 있고 **지금도 존재하는** 파일의 절대 경로.
- `video_id`: `v=<ID>`, `youtu.be/<ID>`, `/shorts/<ID>`, `/live/<ID>`, `/embed/<ID>` 에서 뽑는다. ID 는 `[A-Za-z0-9_-]{11}`. 유튜브 주소가 아니거나 못 찾으면 None.
- `downloads_from_info`: yt-dlp info (재생목록이면 `entries`) 에서 항목마다 `(id, [requested_downloads 의 filepath 중 실제로 있는 파일])`. id 나 파일이 없는 항목은 뺀다.

## 앱별 변경

### 다운로드 탭 (`main.py`)

- 받는 위치가 보관함이 된다. 폴더 줄의 글자는 보관함 경로. `폴더 열기` 는 보관함을 연다. `저장 폴더 선택` 은 지금처럼 저장 폴더를 고른다.
- `다운로드` 를 누르면, 재생목록 전체 받기가 아니고 `video_id(url)` 이 있고 `find_downloaded` 가 파일을 돌려줄 때 묻는다:
  제목 `이미 받은 곡`, 본문 `이 링크는 이미 보관함에 있어요.\n\n<파일 이름들, 줄바꿈으로>\n\n그래도 다시 받을까요?` (`messagebox.askyesno`). 아니오면 아무것도 하지 않는다.
- 다운로드가 끝나면 (키 조정이 있으면 조정까지 끝난 **최종 파일**로) `record_download` 하고, 보관함이 바뀌었다고 알린다 (스템 탭이 목록을 새로 읽는다).
- 완료 문구: `완료. 보관함에 저장했어요.`

### 스템 분리 탭 (`stems_page.py`)

- `파일 선택` 줄 아래에 한 줄 추가: 글자 `보관함에서 선택`, 드롭다운, `새로고침` 버튼.
  - 드롭다운 항목은 `menu_labels(list_songs(보관함))`. 맨 위에 안내 항목 `(보관함에서 고르기)`. 곡이 없으면 `(받은 곡이 없어요)` 하나만.
  - 곡을 고르면 `파일 선택` 으로 고른 것과 똑같이 동작한다 (파일이 링크보다 우선, 파일 이름 표시). `지우기` 를 누르면 드롭다운도 안내 항목으로 돌아간다.
- 링크로 받을 때도 보관함에 받고 `record_download` 한다.
- 결과는 `<보관함>/<곡 이름>_stems/` 에 저장한다.
- 목록을 다시 읽는 때: 시작할 때, `새로고침`, 저장 폴더를 바꿨을 때, 다운로드나 분리가 끝났을 때.

### 템포 추종 (`tempofollow/app.py`)

- `곡 파일` 줄 아래에 한 줄 추가: 글자 `보관함`, 드롭다운(너비 약 260), `새로고침` 버튼.
  - 항목은 `menu_labels(list_tracks(보관함))`. 안내 항목과 빈 목록 문구는 스템 탭과 같다.
  - 고르면 `파일 선택` 으로 고른 것과 똑같이 불러온다. 재생 중에는 고를 수 없다 (지금 `파일 선택` 과 같은 규칙).
- 보관함 위치는 `library_dir(base_dir())`. `새로고침` 때 설정을 다시 읽는다 (다운로드 앱에서 저장 폴더를 바꿨을 수 있다).
- 창 높이를 늘려 기존 요소가 잘리지 않게 한다.

## 허브 자체 업데이트 판정 변경 (v1.1.0 에서 발견한 문제)

v1.1.0 허브는 자기 파일의 해시가 매니페스트와 다르면 "허브 새 버전" 이라고 한다.
그런데 허브는 릴리스마다 다시 빌드되고 빌드 결과는 매번 바이트가 달라서, 허브 코드가 안 바뀌어도 릴리스마다 업데이트하라고 나온다.

- `hub/core.py` 에 `HUB_VERSION = "1.2.0"` (허브 코드가 마지막으로 바뀐 릴리스). 허브 코드를 고칠 때만 올린다.
- 매니페스트 `hub` 에 `"version"` 추가 (`tools/make_manifest.py` 가 `hub/core.py` 에서 읽는다).
- 판정: 매니페스트에 `hub.version` 이 있으면 `HUB_VERSION` 과 다를 때만 업데이트 있음. 없으면(옛 매니페스트) 기존 해시 비교.
- v1.1.0 허브와의 호환: v1.1.0 의 매니페스트 읽기는 모르는 키를 무시하므로 새 매니페스트를 읽을 수 있다.
  v1.1.0 허브는 v1.2.0 에서 한 번 업데이트 안내를 띄우고, 그 뒤로는 허브 코드가 바뀔 때만 띄운다.

## 옮겨 가기

예전에 저장 폴더에 바로 받은 파일은 옮기지 않는다 (사용자 파일을 몰래 옮기지 않는다). 보관함 폴더에 직접 넣으면 목록에 나온다. README 에 적는다.

## 검증

- 단위 테스트: `tests/test_library.py` (폴더 규칙, 목록 순서와 필터, 묶음, 라벨 줄이기와 겹침, 색인 읽기·쓰기·깨진 파일, 영상 ID, info 해석).
- 화면: 기존 GUI 테스트 방식(디스플레이 없으면 skip)으로 스템 탭 드롭다운이 보관함을 반영하는지, 곡을 고르면 file_path 가 바뀌는지.
- 허브: 판정 규칙 테스트, make_manifest 가 version 을 넣는지.
- 산출물: CI 묶음 검증 통과. 실제 PC 에서 v1.1.0 설치 상태 → v1.2.0 업데이트 때 받은 묶음 확인 (풀 버전은 `app` 하나여야 한다).
- 사람만 확인 가능: 드롭다운 모양, 허브 화면의 업데이트 버튼, 실제 유튜브 다운로드(회선 차단이 풀렸을 때).
