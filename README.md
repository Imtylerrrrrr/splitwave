# 🎵 유튜브 오디오 다운로더

유튜브 링크를 붙여넣으면 최고 음질의 오디오(MR/반주)를 다운로드하는 Windows GUI 프로그램입니다.

## 1. 개발 환경 설치 (개발자용)

```bash
# Python 3.11 이상 필요
pip install -r requirements.txt
python main.py
```

> ⚠️ **yt-dlp는 유튜브 측 변경으로 자주 깨집니다.**
> 다운로드가 갑자기 안 되면 가장 먼저 아래 명령으로 최신 버전으로 업데이트하세요:
> ```bash
> pip install -U yt-dlp
> ```
> (exe로 배포한 경우엔 최신 yt-dlp로 다시 빌드해서 전달하면 됩니다.)

## 2. FFmpeg 구하고 배치하기 (Windows)

MP3/WAV 변환에는 FFmpeg가 필요합니다.

1. https://www.gyan.dev/ffmpeg/builds/ 접속
2. **"ffmpeg-release-essentials.zip"** 다운로드
3. 압축 해제 후 `bin` 폴더 안의 **`ffmpeg.exe`** 하나만 복사
4. 이 프로젝트 폴더(= `main.py` 옆)에 붙여넣기

프로그램은 ffmpeg를 이 순서로 자동으로 찾습니다:
1. exe 안에 번들된 ffmpeg (PyInstaller `--add-binary`로 포함한 경우)
2. 실행파일/스크립트와 같은 폴더의 `ffmpeg.exe`
3. 시스템 PATH

> 참고: "원본 최고음질 (재인코딩 없음)" / "(m4a)" 옵션은 FFmpeg 없이도 동작합니다.

## 3. 단일 .exe로 빌드하기 (PyInstaller)

```bash
pip install pyinstaller
```

`ffmpeg.exe`를 `main.py` 옆에 둔 상태에서 (Windows에서 실행):

```bash
pyinstaller --onefile --noconsole --name "유튜브오디오다운로더" --collect-all customtkinter --add-binary "ffmpeg.exe;." main.py
```

- `--onefile` : 단일 exe 생성
- `--noconsole` : 검은 콘솔 창 숨김
- `--collect-all customtkinter` : customtkinter 테마/에셋 포함 (없으면 실행 시 에러)
- `--add-binary "ffmpeg.exe;."` : ffmpeg를 exe 안에 번들 → 친구는 exe 하나만 받으면 됨
- 아이콘을 넣으려면 `--icon icon.ico` 추가

빌드 결과물: **`dist\유튜브오디오다운로더.exe`** — 이 파일 하나만 전달하면 끝.

> 💡 ffmpeg를 번들하지 않으려면 `--add-binary` 옵션을 빼고,
> 친구에게 exe와 `ffmpeg.exe`를 같은 폴더에 두라고 안내하세요. (exe 용량이 가벼워짐)

> ⚠️ Windows Defender가 PyInstaller exe를 오탐할 수 있습니다.
> "추가 정보 → 실행"을 누르거나, Defender 예외에 추가하면 됩니다.

## 4. 사용법 (친구용)

1. exe 더블클릭으로 실행
2. 유튜브 링크 붙여넣기 (재생목록 링크면 "전체 / 첫 영상만" 선택창이 뜸)
3. 포맷 선택:
   - **원본 최고음질 (재인코딩 없음)** — 진짜 최고 음질 (단 .webm일 수 있음)
   - **원본 최고음질 (m4a)** — 편집 프로그램(DAW) 호환성 좋음
   - **MP3 320kbps** — 어디서나 재생되는 호환성 최강
   - **WAV** — 편집 편의용
4. (선택) **키 조정**: 드롭다운에서 반음 단위로 -6 ~ +6 선택
   - 다운로드 시 적용: 키를 골라두고 다운로드하면 키 변환된 파일이 저장됨
   - 기존 파일에 적용: **🎹 기존 파일 키 조정** 버튼 → 내 컴퓨터의 음원 선택
     → 같은 폴더에 `원본이름 (키+2).mp3` 같은 새 파일 생성 (원본 보존)
   - 템포(속도)는 그대로 유지되고 음높이만 바뀝니다 (FFmpeg 필요)
5. 저장 폴더 선택 (기본: 다운로드 폴더, 마지막 폴더 자동 기억)
6. **다운로드** 클릭 → 진행률 확인 → 완료되면 **폴더 열기**

> 🎧 참고: 유튜브 원본 오디오는 Opus 약 160kbps가 상한이라,
> MP3 320k나 WAV로 변환해도 실제 음질이 더 좋아지지는 않습니다.
> (호환성 때문에 변환하는 것일 뿐)
