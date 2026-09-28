# Splitwave Hub 설계

작성 2026-09-28. 브랜치 `hub` (기반: `tempofollow`).

## 목적

동아리원이 파일 하나(허브)만 받으면 앱을 설치, 업데이트, 삭제, 실행할 수 있게 한다.

- 허브 실행파일은 구글 드라이브 공유 폴더와 GitHub Release 에 둔다.
- 앱 파일은 허브가 GitHub Release 에서 받는다.
- 대상 앱 3개: `splitwave`(다운로드+키 조정), `splitwave-full`(스템 분리 포함), `tempofollow`(템포 추종, 실험).

사용자가 확정한 것 (2026-09-28): 직접 만드는 허브, 업데이트 기능 포함, 템포 추종 앱 포함, 드라이브 공유.

## 범위 밖

코드 서명, 바로가기 생성, 백그라운드 자동 업데이트, macOS 배포, 매니페스트 서명, 이어받기.

## 파일 구조

```
hub/__init__.py      빈 파일
hub/core.py          GUI 없는 핵심 로직 (표준 라이브러리만)
hub/cli.py           명령줄 진입 + selftest
hub/app.py           customtkinter 화면
hub_main.py          PyInstaller 진입 스크립트 (hub.cli.main 호출)
tempofollow_main.py  템포 추종 앱의 PyInstaller 진입 스크립트 (--selftest 처리)
tempofollow/selftest.py
tools/apps.json      앱 목록 정의 (매니페스트의 원본)
tools/make_manifest.py
VERSION              릴리스 버전 한 줄 (예: 1.1.0)
```

## 매니페스트 (schema 1)

릴리스 자산 `manifest.json`. `tools/make_manifest.py` 가 만든다.

```json
{
  "schema": 1,
  "version": "1.1.0",
  "hub": {"file": "splitwave-hub.exe", "size": 123, "sha256": "<hex64>"},
  "apps": [
    {
      "id": "splitwave",
      "name": "Splitwave",
      "description": "유튜브 음원 다운로드와 키 조정",
      "exe": "splitwave.exe",
      "parts": [
        {"id": "app", "file": "splitwave.exe", "size": 123, "unpacked": 123,
         "sha256": "<hex64>", "content": "<hex64>"}
      ]
    }
  ]
}
```

- `parts[].file` 이 `.zip` 으로 끝나면 앱 폴더에 풀고, 아니면 파일 그대로 앱 폴더에 복사한다.
- `sha256` 은 받은 파일의 무결성 확인용. `content` 는 내용 동일성 판단용.
  - zip 의 `content`: 디렉터리 항목을 뺀 멤버를 경로순으로 정렬해 `"{경로}\0{그 파일 바이트의 sha256 hex}\n"` 을 이어 붙인 UTF-8 바이트의 sha256.
    zip 을 다시 만들어 타임스탬프가 달라져도 내용이 같으면 값이 같다.
  - 일반 파일의 `content`: 파일의 sha256 과 같다.
- `unpacked`: 풀었을 때 총 바이트 (일반 파일은 `size` 와 같다).
- `exe`: 앱 폴더 기준 상대 경로. `/` 구분.
- 한 앱의 part 들은 같은 경로의 파일을 가질 수 없다 (make_manifest 가 검사).

### 검증 규칙 (허브가 매니페스트를 읽을 때)

하나라도 어기면 `HubError`.

- `schema` 가 1 보다 크면 "허브 업데이트 필요" 문구, 1 이 아니거나 없으면 "형식 오류" 문구.
- `version`: `^[0-9]+(\.[0-9]+){1,3}$`
- 앱 `id`, part `id`: `^[a-z0-9][a-z0-9-]*$`
- `file`: `^[A-Za-z0-9][A-Za-z0-9._-]*$` (경로 구분자 없음)
- `sha256`, `content`: `^[0-9a-f]{64}$`
- `size`, `unpacked`: 0 보다 큰 정수
- `exe`: 절대 경로 아님, 백슬래시 없음, `..` 구성요소 없음, 드라이브 문자 없음
- 앱 id 중복 없음, 한 앱 안의 part id 중복 없음, part 1개 이상

## 주소

```
REPO_URL = "https://github.com/Imtylerrrrrr/splitwave"
매니페스트: {REPO_URL}/releases/latest/download/manifest.json
자산:       {REPO_URL}/releases/download/v{version}/{file}
```

자산 주소에 버전을 넣는 이유: 매니페스트를 읽은 뒤 새 릴리스가 올라와도 해시가 어긋나지 않게.
허브가 주소를 직접 만든다. 매니페스트는 주소를 담지 않는다.

시험용 재정의: `--base URL` 을 주면 매니페스트는 `{base}/manifest.json`, 자산은 `{base}/{file}`.
운영 주소는 https 만 쓴다. 리다이렉트 뒤 최종 주소도 https 여야 한다 (재정의 시에는 검사 안 함).
인증서 검증을 끄지 않는다.

## 설치 위치와 상태

```
<root>/apps/<app_id>/...   앱 파일
<root>/downloads/          받는 중인 파일 (*.part), 끝나면 지움
<root>/state.json
<root>/hub.log
```

- `<root>` 기본값: 환경변수 `LOCALAPPDATA` 가 있으면 `%LOCALAPPDATA%\Splitwave`, 없으면 `~/.local/share/Splitwave`. `--root DIR` 로 재정의.
- `state.json`:

```json
{"schema": 1, "apps": {"splitwave": {
  "name": "Splitwave", "version": "1.1.0", "exe": "splitwave.exe",
  "parts": {"app": {"content": "<hex64>", "files": ["splitwave.exe"]}}}}}
```

- 저장은 임시 파일에 쓰고 `os.replace` 로 바꾼다.
- 읽기 실패(없음, 깨짐)는 빈 상태로 취급한다.

## 동작 규칙

### 상태 판정

part 가 최신인 조건: state 의 같은 part id 의 `content` 가 매니페스트와 같고, 그 part 의 `files` 가 전부 디스크에 있다.

- 설치 기록 없음: `NOT_INSTALLED`
- 모든 part 최신이고 state 에 매니페스트에 없는 part 가 없음: `UP_TO_DATE`
- 그 외: `UPDATE_AVAILABLE`
- 받을 크기 = 최신이 아닌 part 의 `size` 합.

### 설치와 업데이트 (같은 함수)

1. 받을 part(최신 아님)와 없앨 part(state 에는 있고 매니페스트에는 없음)를 구한다. 둘 다 없으면 끝.
2. 앱이 실행 중이면 중단 (아래 "실행 중 판정").
3. 빈 공간 검사: `받을 size 합 + 받을 unpacked 합 + 50 MB` 이상이어야 한다.
4. 받을 part 를 모두 `<root>/downloads/<file>.part` 로 받는다. 받으면서 sha256 을 계산하고, 크기와 sha256 이 다르면 파일을 지우고 중단.
   모든 part 를 받고 검증한 뒤에야 앱 폴더를 건드린다.
5. part 마다 차례로:
   - state 에서 그 part 기록을 지우고 저장한다 (중간에 끊기면 다음에 다시 설치되게).
   - 이전 기록의 `files` 를 지운다.
   - zip 이면 푼다, 아니면 복사한다. 설치한 파일의 상대 경로 목록을 모은다.
   - state 에 `{content, files}` 를 기록하고 저장한다.
6. 없앨 part 의 `files` 를 지우고 기록을 지운다.
7. 앱 기록의 `name`, `version`, `exe` 를 매니페스트 값으로 갱신하고 저장한다.
8. 빈 폴더를 정리하고 `<root>/downloads/` 의 파일을 지운다.

### zip 풀기 안전 규칙

멤버마다: 디렉터리 항목은 건너뛴다. 이름의 `\` 는 `/` 로 바꿔 해석한다.
절대 경로, 드라이브 문자(`C:`), `..` 구성요소, 빈 이름, 심볼릭 링크 속성이 있으면 전체를 거부한다 (아무것도 풀지 않음: 먼저 전 멤버를 검사한 뒤 푼다).
대상 경로를 resolve 한 결과가 앱 폴더 밖이면 거부.

### 삭제

state 에 기록된 모든 part 의 `files` 를 지우고, 빈 폴더를 정리하고, 앱 폴더가 비면 지운다. 기록에 없는 파일은 건드리지 않는다.
실행 중이면 중단.

### 실행 중 판정

Windows 에서만: `<앱 폴더>/<exe>` 를 `open(path, "r+b")` 로 열어 `PermissionError` 면 실행 중. 그 외 OS 는 항상 아님.

### 실행

```python
env = os.environ.copy()
env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
for k in list(env):
    if k.startswith("_PYI_") or k == "_MEIPASS2":
        del env[k]
if os.name == "nt":
    ctypes.windll.kernel32.SetDllDirectoryW(None)
subprocess.Popen([exe, *args], cwd=exe.parent, env=env)
if os.name == "nt" and hasattr(sys, "_MEIPASS"):
    ctypes.windll.kernel32.SetDllDirectoryW(sys._MEIPASS)   # 허브 쪽 검색 경로는 되돌린다
```

`hub.core.spawn(cmd, cwd=None)` 이 이 규칙을 구현한다. 앱 실행과 허브 재시작이 모두 이것을 쓴다.

이유: 허브도 앱도 PyInstaller 빌드라, 허브의 환경변수와 DLL 검색 경로가 자식에게 넘어가면 자식이 허브의 임시 폴더를 자기 것으로 착각한다.

### 허브 자체 업데이트

- 업데이트 있음 판정: `sys.frozen` 이고, 자기 실행파일(`sys.executable`)의 sha256 이 매니페스트 `hub.sha256` 과 다름. 소스로 실행 중이면 항상 없음.
- 절차: 새 파일을 자기 실행파일과 같은 폴더의 `<이름>.new` 로 받고 검증 → 기존 `<이름>.old` 삭제 → 실행 중인 자기 파일을 `<이름>.old` 로 이름 변경 → `.new` 를 원래 이름으로 변경 → 새 파일을 "실행" 규칙의 환경으로 띄우고 종료.
- 시작할 때 `<이름>.old` 가 있으면 지운다 (실패는 무시).
- 실패하면: "허브를 새 버전으로 바꾸지 못했어요. 새 허브를 직접 받아 주세요."

## 명령줄

```
splitwave-hub [--root DIR] [--base URL]                 화면 실행
splitwave-hub --selftest [--root DIR]                   0 = 정상. 기록은 <root>/hub.log (root 기본값: 임시 폴더)
splitwave-hub cli [--root DIR] [--base URL] status
splitwave-hub cli [--root DIR] [--base URL] install APP
splitwave-hub cli [--root DIR] [--base URL] remove APP
splitwave-hub cli [--root DIR] [--base URL] run APP [--wait] [-- ARGS...]
```

- 종료 코드: 0 정상, 1 `HubError`(문구를 stderr 와 hub.log 에), 2 사용법 오류. `run --wait` 는 앱의 종료 코드를 그대로 돌려준다.
- `status` 는 앱마다 한 줄: `<id>\t<상태>\t<설치 버전 또는 ->\t<받을 바이트>`.
- `--noconsole` 빌드에서는 stdout 이 없을 수 있다. 출력 실패는 무시하고 hub.log 에는 항상 남긴다.

### selftest (네트워크·화면 없이)

1. `assets/theme.json`, `assets/icon.png`, `assets/icon.ico` 가 `common.resource_path` 로 열리는지.
2. `import customtkinter` 가 되는지, `ssl.create_default_context()` 가 되는지.
3. 임시 폴더에 가짜 릴리스(zip part 1개 + 일반 파일 part 1개)를 만들고 127.0.0.1 임시 포트의 HTTP 서버로 제공 →
   설치 → 파일 확인 → part 하나만 바꾼 매니페스트로 업데이트 → 바뀐 part 만 받았는지(서버 요청 기록) 확인 → 삭제 → 파일 없음 확인.
4. 실패하면 이유 한 줄을 stderr 와 hub.log 에 쓰고 1. 예상 못 한 예외도 잡아서 같은 방식으로 기록한다.
5. selftest 는 사용자의 실제 설치 폴더를 건드리지 않는다 (가짜 릴리스와 설치는 전부 임시 폴더).

앱 쪽 selftest 기록: 환경변수 `SELFTEST_LOG` 가 있으면 `tempofollow_main.py --selftest` 는 stdout 과 stderr 를 그 파일로 보낸다
(창 없는 빌드는 콘솔 출력이 보이지 않아서, CI 가 실패 이유를 읽을 수 있게).

## 화면

창 제목 `Splitwave Hub`, 520x600, `assets/theme.json` 과 아이콘 사용 (기존 앱과 같은 방식). 이모지 금지.

- 맨 위: 제목, 그 아래 한 줄 상태 (`최신 버전 v1.1.0` 또는 `목록을 가져오지 못했어요`), `다시 확인` 버튼.
- 허브 업데이트가 있을 때만 보이는 줄: `허브 새 버전이 있어요` + `허브 업데이트` 버튼.
- 앱마다 카드: 이름, 설명, 상태 문구, 버튼.
  - 설치 안 됨: `설치`
  - 최신: `실행`, `삭제`
  - 업데이트 있음: `업데이트`, `실행`, `삭제`
- 맨 아래: 진행 막대와 상태 문구. 작업 중에는 모든 버튼 비활성.
- 작업은 별도 스레드에서, 화면 갱신은 `after` 로.
- 목록을 못 가져와도 state 에 있는 앱은 카드로 보여 주고 `실행`, `삭제` 가 된다. 상태 문구는 `설치됨 v1.1.0 (업데이트 확인 실패)` (확인을 못 했으므로 `최신` 이라고 하지 않는다).

상태 문구:

```
설치 안 됨 · 받을 크기 27 MB
설치됨 v1.1.0 · 최신
업데이트 있음 v1.1.0 → v1.2.0 · 받을 크기 47 MB
```

## 오류 문구 (HubError)

| 상황 | 문구 |
|---|---|
| 네트워크 | 인터넷에 연결하지 못했어요. 연결을 확인하고 다시 시도해 주세요. |
| 해시·크기 불일치 | 받은 파일이 손상됐어요. 다시 시도해 주세요. |
| 실행 중 | 앱이 실행 중이에요. 앱을 닫고 다시 시도해 주세요. |
| 공간 부족 | 디스크 공간이 부족해요. 약 {n} MB가 필요해요. |
| 매니페스트 형식 | 설치 목록 형식이 올바르지 않아요. 허브를 새로 받아 주세요. |
| schema 가 더 새로움 | 이 허브로는 새 목록을 읽을 수 없어요. 허브를 업데이트해 주세요. |
| zip 경로 위반 | 설치 파일에 허용되지 않는 경로가 있어요. |
| 미설치 앱 실행·삭제 | 설치되지 않은 앱이에요. |
| 매니페스트에 없는 앱 | 목록에 없는 앱이에요. |
| 허브 교체 실패 | 허브를 새 버전으로 바꾸지 못했어요. 새 허브를 직접 받아 주세요. |

## 보안 메모

- 받는 곳은 코드에 고정된 저장소 하나. https, 인증서 검증, sha256 대조.
- 해시는 전송 중 손상과 부분 다운로드를 막는다. 저장소 계정이 탈취된 경우는 막지 못한다 (그 경우 허브 자체도 바뀔 수 있으므로 매니페스트 서명은 하지 않는다).
- `--base` 는 시험용. 명령줄 인자를 줄 수 있는 사람은 이미 임의 프로그램을 실행할 수 있다.

## 빌드와 릴리스

CI (`.github/workflows/build-windows.yml`) 에 추가:

- `build-tempofollow`: onedir, ffmpeg 번들, `--selftest` 통과 후 `tempofollow.zip` (최상위 폴더 `tempofollow/`).
- `build-hub`: onefile `splitwave-hub.exe`, `--selftest` 통과.
- `package` (위 빌드 전부 필요): 자산을 `release/` 에 모으고 `tools/make_manifest.py` 실행 →
  로컬 HTTP 서버로 `release/` 를 제공하고 빌드된 허브로 세 앱을 설치, `run --wait -- --selftest`, 삭제 → `release` 아티팩트 업로드.

릴리스: `VERSION` 을 올리고 main 에 푸시 → CI 통과 → `gh run download -n release` → `gh release create v<VERSION> release/*`.

## 2단계 (바뀐 부분만 받기)

`splitwave-full` 을 네 part 로 나눈다 (`tools/split_parts.py`, 규칙은 `tools/apps.json` 의 `split`). 허브 코드는 바뀌지 않는다.
직접 받는 사람을 위한 통짜 `splitwave-full.zip` 도 릴리스에 그대로 둔다.

| part | 내용 | 받는 크기 (v1.1.0 실측) | 2026-09-25 빌드와 내용 동일 |
|---|---|---|---|
| `torch` | `_internal/torch/`, `_internal/numpy/`, `_internal/numpy.libs/` | 108.5 MB | 같음 |
| `model` | `_internal/hf_home/` | 50.8 MB | 같음 |
| `runtime` | 나머지 (파이썬, Tcl/Tk, ffmpeg 등) | 21.7 MB | 같음 |
| `app` | 실행파일, `base_library.zip`, `*.dist-info/` | 33.1 MB | 다름 |

- 업데이트는 보통 `app` 33 MB 만 받는다 (통짜는 209 MB).
- 처음 설치는 214 MB 로 통짜보다 5 MB 크다 (7z 대신 파이썬 zlib 로 압축해서). 테스트 가능한 단일 경로를 택한 대가.
- `*.dist-info/RECORD` 는 빌드마다 달라져서 torch 쪽이 아니라 `app` 에 넣는다.
- torch, numpy 버전은 `constraints-full.txt` 로 고정한다.
- 어느 part 가 바뀌든 허브는 `content` 로 판단하므로, 고정이 풀려도 결과는 "더 받는다" 일 뿐 설치가 틀어지지는 않는다.

## 검증 계획

- 단위 테스트: 로컬 HTTP 서버와 합성 zip 으로 설치, 업데이트(바뀐 part 만), 삭제, 해시 불일치, zip 경로 위반, 매니페스트 검증, 상태 판정.
- 산출물 검증 (Mac): 실제 빌드 파일로 매니페스트를 만들고 허브 코어로 설치해 파일 수와 총 바이트가 zip 과 같은지 확인.
  옛 빌드 설치 → 새 빌드로 업데이트 때 `app` 하나만 받고 결과가 새 zip 과 파일 단위로 같은지 확인.
- CI (Windows 서버): 빌드된 허브가 빌드된 앱을 설치하고 실행(selftest)까지.
- 사람만 확인 가능: 경고창, 백신 반응, 화면 모양, 실제 오디오 장치.
