<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo.svg">
  <img src="assets/logo-light.svg" alt="splitwave" height="64">
</picture>

유튜브 링크나 음원 파일을 넣으면 **최고 음질로 받고, 키를 바꾸고, 악기별 스템(보컬·드럼·기타·건반·베이스)으로 분리하거나 원하는 악기만 뺀 음원을 만들어** 주는 Windows 프로그램입니다.

---

## 다운로드

**`splitwave-hub.exe` 하나만 받으면 돼요.** 허브를 열면 아래 앱을 버튼으로 설치, 업데이트, 삭제, 실행할 수 있어요.

| 앱 | 기능 | 받는 크기 |
|---|---|---|
| Splitwave | 다운로드 + 키 조정 | 약 27 MB |
| Splitwave + 스템 분리 | 위 기능 + **스템 분리** | 약 214 MB (분리 모델 포함). 업데이트는 보통 33 MB |
| Tempo Follow (실험) | 드럼 템포를 따라가며 곡 재생 | 약 32 MB |

→ [Releases 페이지](https://github.com/Imtylerrrrrr/splitwave/releases/latest)에서 `splitwave-hub.exe`(약 15 MB)를 받으세요. 파이썬·FFmpeg 설치 필요 없어요.

- 앱은 `%LOCALAPPDATA%\Splitwave` 아래에 설치돼요. 관리자 권한이 필요 없어요.
- 새 버전이 나오면 허브에 `업데이트` 버튼이 보여요. 받은 파일은 허브가 해시를 자동으로 대조해요.
- Splitwave 두 가지는 하나만 설치하면 돼요. 스템 분리가 필요하면 아래쪽 것을 고르세요.

허브 없이 직접 받고 싶으면 같은 페이지에서 받을 수 있어요.

| | 라이트 `splitwave.exe` | 풀 `splitwave-full.zip` |
|---|---|---|
| 용량 | 약 27 MB | 약 209 MB (분리 모델 포함) |
| 실행 | exe 더블클릭 | 압축 풀고 **폴더 안의** `splitwave-full.exe` 실행 (exe만 꺼내면 안 됨) |

> **처음 실행하면 Windows가 "알 수 없는 게시자" 경고를 띄워요.** 개인이 만든 프로그램이라 유료 서명 인증서가 없어서 그래요. "**추가 정보 → 실행**"을 누르면 됩니다.

## 사용법

**곡 보관함**

받은 곡과 분리한 스템은 `저장 폴더/Splitwave` 폴더(보관함)에 모여요. 저장 폴더의 기본값은 다운로드 폴더예요.
세 앱(다운로드, 스템 분리, Tempo Follow)이 같은 보관함을 보기 때문에, 받아 둔 곡을 목록에서 바로 고를 수 있어요.

```
Splitwave/
  곡 제목.m4a            받은 곡
  곡 제목_stems/         스템 분리 결과 (보컬.wav, 드럼.wav, 기타 제거.wav ...)
```

- 가지고 있던 음원을 이 폴더에 직접 넣어도 목록에 나와요.
- v1.1.0 까지 저장 폴더에 바로 받았던 파일은 자동으로 옮기지 않아요. 목록에서 쓰려면 보관함 폴더로 옮기세요.

**다운로드 탭**
1. 유튜브 링크 붙여넣기 (재생목록이면 전체/첫 곡 선택 가능)
2. 포맷 선택 — 기본 m4a. 원본/m4a는 음질 손실 없음, MP3·WAV로 바꿔도 더 좋아지진 않아요
3. 키 조정 — 반음 단위 ±6, 템포는 그대로
4. `다운로드` → 보관함에 저장. 이미 받은 링크면 알려 주고 다시 받을지 물어요. `기존 파일 키 조정`으로 이미 있는 파일도 키만 바꿀 수 있어요

**스템 분리 탭** (풀 버전)
1. 유튜브 링크, `파일 선택`, `보관함에서 선택` 중 하나 (파일이나 보관함에서 고른 곡이 링크보다 우선)
2. 저장할 스템 선택 — 기본: 보컬·드럼·기타·건반·베이스. `그외`는 나머지 소리
3. 빼고 듣기 — 체크한 악기만 뺀 음원을 따로 저장해요 (예: 기타를 체크하면 `기타 제거.wav`). 연습할 때 자기 파트만 빼고 틀어 놓는 용도예요
4. 출력 포맷(WAV/MP3)·키 조정 선택 → `분리 시작` (저장할 스템과 빼고 듣기 중 하나만 골라도 돼요)
5. 보관함에 `<곡이름>_stems/` 폴더가 생기고 `보컬.wav`, `드럼.wav`, `기타 제거.wav` … 가 들어 있어요

- 분리는 CPU로 돌아가요. 3~4분 곡 기준 **수 분** 걸립니다.
- 기타·건반 분리 품질은 보컬·드럼보다 낮은 편이에요 (모델 한계).
- 빼고 듣기의 품질도 분리 품질과 같아요. 기타를 뺀 음원에는 기타 소리가 조금 남을 수 있어요.

## 이 파일이 안전한지 확인하는 법

- **소스코드가 이 저장소에 전부 있어요.** 실행파일은 제 컴퓨터가 아니라 **GitHub Actions**(GitHub의 Windows 서버)가 이 소스로 자동 빌드한 거예요. 어떤 코드로 어떻게 만들었는지 [Actions 탭](https://github.com/Imtylerrrrrr/splitwave/actions)의 빌드 로그에서 볼 수 있어요.
- **해시 확인** — Release 페이지의 `SHA256SUMS.txt`와 받은 파일의 해시가 같으면 중간에 바뀐 게 없는 거예요. PowerShell에서:
  ```powershell
  Get-FileHash splitwave-full.zip
  ```
- **백신 검사** — 받은 파일을 [VirusTotal](https://www.virustotal.com/)에 직접 올려 확인할 수 있어요. PyInstaller로 만든 프로그램은 백신 몇 개가 오탐을 내는 게 흔해요(2~3/70 정도).

## 자주 묻는 것

- **다운로드가 갑자기 안 돼요** — 유튜브가 바뀌면 yt-dlp가 깨져요. 허브에서 `업데이트`를 누르거나 새 버전을 Releases에서 받으세요. (소스로 쓰는 경우 `pip install -U yt-dlp`)
- **"유튜브가 이 인터넷 연결을 자동 프로그램으로 의심해서 막았습니다"라고 나와요** — 프로그램 고장이 아니라 유튜브가 그 인터넷 회선을 막은 거예요. 휴대폰 핫스팟처럼 다른 인터넷으로 바꾸거나 몇 시간 뒤에 다시 시도하세요. 새 버전으로 바꿔도 해결되지 않아요.
- **맥에서는?** — 실행파일은 Windows용이에요. 맥은 아래 개발자용 항목대로 소스로 실행하면 됩니다.
- **인터넷 없어도 되나요?** — 유튜브 다운로드만 인터넷이 필요해요. 파일 분리·키 조정은 오프라인에서 돼요.

---

## 사이드 앱: 템포 추종 재생 (실험)

드러머가 치는 박자를 마이크로 듣고 템포(BPM)를 실시간으로 추정해서, 곡을 그 템포에 맞춰 **음높이는 그대로 두고 속도만 바꿔** 재생합니다.
스템 분리로 드럼을 뺀 곡을 틀어 놓고 드러머가 자기 템포로 치면 곡이 따라오는 용도예요. Windows 는 허브에서 `Tempo Follow (실험)`을 설치하면 되고, 소스로도 실행할 수 있어요.

```bash
pip install -r requirements-tempofollow.txt
python -m tempofollow
```

1. `보관함` 드롭다운에서 곡이나 스템을 고른다 (예: `곡 제목 / 건반`). 다른 곳의 파일은 `파일 선택`으로 고른다.
2. `기본 BPM`에 곡의 템포를 넣는다 (모르면 `곡에서 추정`).
3. 마이크와 출력 장치를 고르고 `시작`을 누른다.
4. 드럼을 치기 시작하면 재생이 시작되고, 치는 템포를 따라간다 (멈추면 마지막 템포 유지).

- 스피커로 나간 앱 소리가 마이크로 되돌아오면 앱이 지연을 찾아 상쇄하고, 드럼이 아닌 소리(연속 측정이 서로 안 맞는 소리)는 무시해요. 그래도 마이크를 드럼 가까이 두거나 믹서 aux 센드로 드럼 채널만 앱에 넣으면 훨씬 빨리, 정확히 따라가요.
- 재생을 시작하고 처음 10초쯤은 기본 BPM으로 틀어요 (새어 드는 소리를 확인하는 시간). 그 뒤 템포 변화는 3~4초 늦게 반영돼요. 드럼이 작게 들리면 더 느려요.
- 기본 BPM이 크게 틀리면 (추종 범위 밖) 따라가지 못해요.

---

## 개발자용

### 실행

```bash
# Python 3.12
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # 라이트
pip install -r requirements-stems.txt    # 풀 (demucs + torch CPU, ~500MB)
python main.py
```

- 맥 Homebrew 파이썬은 tkinter가 따로예요: `brew install python-tk@3.12` 먼저.
- FFmpeg 필요 (MP3/WAV 변환·키 조정·스템 분리). 맥은 `brew install ffmpeg`, Windows는 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)에서 `ffmpeg-release-essentials.zip` → `bin/ffmpeg.exe`를 `main.py` 옆에 두면 돼요. 프로그램은 번들 → 실행파일 옆 → PATH 순으로 찾아요.
- 소스로 실행할 때 첫 스템 분리에서 모델(약 54 MB)을 HuggingFace에서 자동으로 받아요.
- 테스트: `pip install -r requirements-dev.txt && pytest` (스템 테스트는 1분쯤)
- `python main.py --selftest` — GUI 없이 ffmpeg 확인·모델 로드·1초짜리 분리까지 실행 (종료 코드 0이면 정상)

### 구조

```
main.py          진입점. 창·탭 호스트·다운로드 탭
stems_page.py    스템 분리 탭 (demucs 없으면 안내만 표시)
separator.py     Demucs htdemucs_6s 호출. UI 의존 없음
common.py        공용 헬퍼 (ffmpeg 탐색, 키 조정 필터, 에러 문구 …)
library.py       곡 보관함 (폴더 위치, 목록, 이미 받은 링크 색인, 공용 설정). 세 앱이 같이 씀
assets/          로고·아이콘·테마. make_assets.py 로 재생성
tempofollow/     사이드 앱: 템포 추종 재생 (진입 스크립트 tempofollow_main.py)
hub/             허브: 설치·업데이트 관리자 (진입 스크립트 hub_main.py). core.py 는 표준 라이브러리만 사용
tools/           빌드 도구 (ffmpeg 빌드, 가중치 정리, make_manifest.py, apps.json)
VERSION          릴리스 버전
```

풀/라이트 구분은 코드가 아니라 `import demucs` 가능 여부 하나로만 갈려요.

### 빌드

`main`에 push하면 GitHub Actions가 아래 순서로 만들어요 (`.github/workflows/build-windows.yml`):

- `build-ffmpeg` → 오디오 전용 `ffmpeg.exe`. 공식 소스(버전·SHA-256 고정)를 `tools/ffmpeg/build.sh`로 정적 빌드해요. 영상 코덱을 빼고 오디오 디코더·컨테이너·인코더(libmp3lame, aac, libopus, flac, pcm)만 켜서 11 MB 남짓이에요 (기존 범용 빌드는 159 MB). `tools/ffmpeg/smoke.sh`가 앱이 쓰는 ffmpeg 명령을 전부 실행해 확인하고, 스크립트가 안 바뀌면 캐시를 재사용해요.
- `build-lite` → `splitwave.exe` (PyInstaller onefile, ffmpeg 번들)
- `build-full` → `splitwave-full.zip` (onedir, ffmpeg + Demucs 가중치 번들. 가중치는 한 벌만 넣고, `torch.compile`·ONNX 등 추론에 안 쓰는 모듈은 제외해요)

- `build-tempofollow` → `tempofollow.zip` (onedir, ffmpeg 번들)
- `build-hub` → `splitwave-hub.exe` (onefile. 앱을 담지 않고 릴리스에서 받아 와요)
- `package` → 위 파일을 모으고, 풀 버전을 허브용 묶음 넷으로 나눈 뒤(`tools/split_parts.py`. torch·모델처럼 잘 안 바뀌는 것을 따로 묶어 업데이트 때 바뀐 묶음만 받게 해요), `manifest.json`(허브가 읽는 설치 목록)과 `SHA256SUMS.txt`를 만들고, 빌드된 허브로 빌드된 앱 세 개를 실제로 설치, 실행(`--selftest`), 삭제해 봐요

앱은 모두 빌드 직후 `exe --selftest`를 실행해 번들이 실제로 동작하는지 확인합니다 (풀은 번들 가중치 파일이 있는지 확인하고 실제로 1초짜리 분리까지 돌려요. 최종 zip 안에 가중치가 들어 있는지도 따로 검사해요). 아티팩트는 Actions 탭에서 `gh run download`로 받으면 돼요.

### 릴리스

```bash
# 1) VERSION 을 올리고 docs/release-notes/v<버전>.md 를 쓴 뒤 main 에 push
# 2) 같은 커밋에 버전 태그를 올린다
git tag "v$(cat VERSION)" && git push origin "v$(cat VERSION)"
```

태그를 올리면 Actions 가 빌드와 검증을 다시 돌리고, 통과하면 `release` 작업이 해시를 대조한 뒤 GitHub Release 를 게시해요.
태그와 `VERSION` 이 다르거나 릴리스 노트 파일이 없으면 게시하지 않아요.

허브는 `releases/latest/download/manifest.json` 을 읽어요. 그래서 `manifest.json` 이 없는 릴리스를 최신으로 올리면 허브가 목록을 못 가져와요.

Windows에서 직접 빌드하려면 (`ffmpeg.exe`를 `main.py` 옆에 둔 상태에서. 어떤 ffmpeg든 되지만 CI는 위의 오디오 전용 빌드를 써요):

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name "splitwave" --icon assets/icon.ico --collect-all customtkinter --add-binary "ffmpeg.exe;." --add-data "assets;assets" main.py
```

풀 버전은 워크플로의 `build-full` 단계를 그대로 따라 하세요 — 핵심은 가중치를 `hf_home/`에 미리 받아 `--add-data "hf_home;hf_home"`으로 넣고 `--onedir`로 빌드하는 것.

### 로고·테마 바꾸기

`assets/make_assets.py`에서 색·기하를 고치고 실행하면 `logo.svg`, `icon.png`, `icon.ico`, `mark.png`, `theme.json`이 다시 생성돼요. 생성물도 함께 커밋합니다.
