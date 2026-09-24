<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo.svg">
  <img src="assets/logo-light.svg" alt="splitwave" height="64">
</picture>

유튜브 링크나 음원 파일을 넣으면 **최고 음질로 받고, 키를 바꾸고, 악기별 스템(보컬·드럼·기타·건반·베이스)으로 분리**해 주는 Windows 프로그램입니다.

---

## 다운로드

| | 라이트 `splitwave.exe` | 풀 `splitwave-full.zip` |
|---|---|---|
| 기능 | 다운로드 + 키 조정 | 라이트 + **스템 분리** |
| 용량 | 약 90 MB | 약 400 MB (분리 모델 포함) |
| 실행 | exe 더블클릭 | 압축 풀고 **폴더 안의** `splitwave-full.exe` 실행 (exe만 꺼내면 안 됨) |

→ [Releases 페이지](https://github.com/Imtylerrrrrr/splitwave/releases)에서 받으세요. 파이썬·FFmpeg 설치 필요 없어요.

> **처음 실행하면 Windows가 "알 수 없는 게시자" 경고를 띄워요.** 개인이 만든 프로그램이라 유료 서명 인증서가 없어서 그래요. "**추가 정보 → 실행**"을 누르면 됩니다.

## 사용법

**다운로드 탭**
1. 유튜브 링크 붙여넣기 (재생목록이면 전체/첫 곡 선택 가능)
2. 포맷 선택 — 기본 m4a. 원본/m4a는 음질 손실 없음, MP3·WAV로 바꿔도 더 좋아지진 않아요
3. 키 조정 — 반음 단위 ±6, 템포는 그대로
4. `다운로드` → 저장 폴더에 생성. `기존 파일 키 조정`으로 이미 있는 파일도 키만 바꿀 수 있어요

**스템 분리 탭** (풀 버전)
1. 유튜브 링크 **또는** `파일 선택` (둘 다 있으면 파일 우선)
2. 저장할 스템 선택 — 기본: 보컬·드럼·기타·건반·베이스. `그외`는 나머지 소리
3. 출력 포맷(WAV/MP3)·키 조정 선택 → `분리 시작`
4. 저장 폴더에 `<곡이름>_stems/` 폴더가 생기고 `보컬.wav`, `드럼.wav` … 가 들어 있어요

- 분리는 CPU로 돌아가요. 3~4분 곡 기준 **수 분** 걸립니다.
- 기타·건반 분리 품질은 보컬·드럼보다 낮은 편이에요 (모델 한계).

## 이 파일이 안전한지 확인하는 법

- **소스코드가 이 저장소에 전부 있어요.** 실행파일은 제 컴퓨터가 아니라 **GitHub Actions**(GitHub의 Windows 서버)가 이 소스로 자동 빌드한 거예요. 어떤 코드로 어떻게 만들었는지 [Actions 탭](https://github.com/Imtylerrrrrr/splitwave/actions)의 빌드 로그에서 볼 수 있어요.
- **해시 확인** — Release 페이지의 `SHA256SUMS.txt`와 받은 파일의 해시가 같으면 중간에 바뀐 게 없는 거예요. PowerShell에서:
  ```powershell
  Get-FileHash splitwave-full.zip
  ```
- **백신 검사** — Release 본문의 VirusTotal 링크 참고. PyInstaller로 만든 프로그램은 백신 몇 개가 오탐을 내는 게 흔해요(2~3/70 정도).

## 자주 묻는 것

- **다운로드가 갑자기 안 돼요** — 유튜브가 바뀌면 yt-dlp가 깨져요. 새 버전이 Releases에 올라오면 받으세요. (소스로 쓰는 경우 `pip install -U yt-dlp`)
- **맥에서는?** — 실행파일은 Windows용이에요. 맥은 아래 개발자용 항목대로 소스로 실행하면 됩니다.
- **인터넷 없어도 되나요?** — 유튜브 다운로드만 인터넷이 필요해요. 파일 분리·키 조정은 오프라인에서 돼요.

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
- 소스로 실행할 때 첫 스템 분리에서 모델(약 80 MB)을 HuggingFace에서 자동으로 받아요.
- 테스트: `pip install -r requirements-dev.txt && pytest` (스템 테스트는 1분쯤)
- `python main.py --selftest` — GUI 없이 ffmpeg·모델 로드 확인 (종료 코드 0이면 정상)

### 구조

```
main.py          진입점. 창·탭 호스트·다운로드 탭
stems_page.py    스템 분리 탭 (demucs 없으면 안내만 표시)
separator.py     Demucs htdemucs_6s 호출. UI 의존 없음
common.py        공용 헬퍼 (ffmpeg 탐색, 키 조정 필터, 에러 문구 …)
assets/          로고·아이콘·테마. make_assets.py 로 재생성
```

풀/라이트 구분은 코드가 아니라 `import demucs` 가능 여부 하나로만 갈려요.

### 빌드

`main`에 push하면 GitHub Actions가 두 가지를 만들어요 (`.github/workflows/build-windows.yml`):

- `build-lite` → `splitwave.exe` (PyInstaller onefile, ffmpeg 번들)
- `build-full` → `splitwave-full.zip` (onedir, ffmpeg + Demucs 가중치 번들)

둘 다 빌드 직후 `exe --selftest`를 실행해 번들이 실제로 동작하는지 확인합니다. 아티팩트는 Actions 탭에서 `gh run download`로 받으면 돼요.

Windows에서 직접 빌드하려면 (`ffmpeg.exe`를 `main.py` 옆에 둔 상태에서):

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name "splitwave" --icon assets/icon.ico --collect-all customtkinter --add-binary "ffmpeg.exe;." --add-data "assets;assets" main.py
```

풀 버전은 워크플로의 `build-full` 단계를 그대로 따라 하세요 — 핵심은 가중치를 `hf_home/`에 미리 받아 `--add-data "hf_home;hf_home"`으로 넣고 `--onedir`로 빌드하는 것.

### 로고·테마 바꾸기

`assets/make_assets.py`에서 색·기하를 고치고 실행하면 `logo.svg`, `icon.png`, `icon.ico`, `mark.png`, `theme.json`이 다시 생성돼요. 생성물도 함께 커밋합니다.
