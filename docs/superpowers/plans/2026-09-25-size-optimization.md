# Splitwave 배포 용량 최적화 계획

**목표:** 기능·속도·품질을 그대로 두고 배포 파일을 줄인다. 라이트 exe 90MB → 약 25MB, 풀 zip 407MB → 약 220MB.

**원칙:** 앱 코드는 selftest 강화 외엔 건드리지 않는다. 줄이는 방법은 전부 "안 쓰는 짐 제거"이며, 매 변경은 CI의 실행파일 selftest(실제 분리 포함)로 검증된다.

**브랜치:** `size-opt` (main 머지·push는 사용자 확인 후 컨트롤러가 한다. 구현자는 `size-opt`에만 push.)

**CI 실행:** 워크플로에 `workflow_dispatch`가 있으므로 브랜치에서 `gh workflow run build-windows.yml --ref size-opt` 후 `gh run watch <id>` 또는 `gh run list --workflow build-windows.yml --branch size-opt`. 로그는 `gh run view <id> --log-failed` 로 실패 부분만 본다 (전체 로그를 컨텍스트에 붓지 말 것).

## 측정된 현재 상태 (2026-09-25, v1.0.0 산출물 실측)

| 항목 | 라이트 exe (압축 후 86MB) | 풀 zip (407MB) |
|---|---|---|
| `ffmpeg.exe` (BtbN win64-gpl 풀 빌드, 원본 159MB) | 61 | 61 |
| Demucs 가중치 `5c90dfd2.safetensors` 53.6MB가 3벌 (snapshot / hub blob / xet 캐시, sha256 동일) | - | 144 |
| `torch/lib/torch_cpu.dll` (원본 292MB) | - | 80 |
| PYZ(파이썬 모듈 묶음, 이미 압축돼 zip에서 더 안 줄어듦) | 8 | 43 |
| PYZ 중 미사용: sympy 5.8 + mpmath 0.7 + networkx 1.6 + torch._inductor 4.8 + torch._dynamo 2.1 + torch.onnx 0.5 | - | 15.5 |
| `PIL/_avif.pyd` 7.5MB + `_webp.pyd` | 4.5 | 4.5 |
| `hf_xet/hf_xet.pyd` 10MB | - | 4 |
| `torch/bin` (protoc 등 3MB) | - | 1 |

가중치는 이미 float16으로 저장돼 있다(525 텐서 전부 float16, 27.4M 파라미터 × 2B = 53.6MB). fp16 변환은 할 게 없다.

### "안 쓴다"의 근거

`PYTHONPATH=. .venv/bin/python` 으로 모델 로드 → 2초 분리(`separate_tensor`) → mp3 저장(`demucs.api.save_audio`)까지 실제로 돌린 뒤 `sys.modules` 를 조사한 결과 (torch 2.14.0, Python 3.12.14 — CI와 같은 버전):

- 통째로 로드되지 않은 torch 하위 패키지: `_dynamo`, `_inductor`, `onnx`, `_lazy`, `_numpy`, `nativert`, `numa`, `bin`, `include`, `share`
- 로드되지 않은 서드파티: `sympy`, `mpmath`, `networkx`, `hf_xet`, `setuptools`, `fsspec`, `requests`, `PIL`
- 논리적 이유: `_dynamo/_inductor` = `torch.compile` 컴파일러, `onnx` = 내보내기, `sympy/mpmath/networkx` = 심볼릭 셰이프·fx 그래프 패스용 — demucs 는 eager 추론만 한다. `hf_xet` = 허브 다운로드 가속기 — 배포본은 `HF_HUB_OFFLINE=1` 로 번들 캐시만 읽는다. `PIL._avif/_webp` = AVIF/WebP 코덱 — 앱은 PNG 두 장만 연다.
- **제외하지 않는 것:** `setuptools`(PyInstaller 런타임 훅 의존), `fsspec`/`requests`/`urllib3`(yt-dlp 네트워크 경로는 측정에 포함되지 않았음), `torch.distributed`/`torch.testing`/`torch.fx` 등 일부라도 로드된 패키지.

---

## Task 1: 번들 정리 (가중치 중복 제거, 미사용 모듈 제외, selftest 강화)

**모델:** sonnet. **파일:** `main.py`(selftest만), `tests/test_selftest.py`, `.github/workflows/build-windows.yml`.

### 1-1. selftest 에 실제 분리 추가 (`main.py` `selftest()`)

지금은 풀 빌드에서 `Separator` 생성까지만 확인한다. 모듈 제외가 추론 경로를 깨뜨리지 않았는지 보려면 실제로 한 번 돌려야 한다. 풀 분기를 이렇게 바꾼다:

```python
    if stems_available():
        import torch
        import demucs.api
        from separator import MODEL_NAME, SAMPLE_RATE
        sep = demucs.api.Separator(model=MODEL_NAME, device="cpu", progress=False)
        _, out = sep.separate_tensor(torch.zeros(2, SAMPLE_RATE), SAMPLE_RATE)
        missing = set(sep.model.sources) - set(out)
        if missing:
            print(f"selftest: stems missing {sorted(missing)}", file=sys.stderr)
            return 1
        print(f"selftest: full build ok, stems={list(sep.model.sources)}")
```

`tests/test_selftest.py::test_selftest_full_loads_model` 은 그대로 0을 기대하면 된다 (로컬에서 1초 분리라 몇 초 걸림). `pytest -q tests/test_selftest.py` 통과 확인.

### 1-2. 워크플로 수정 (`.github/workflows/build-windows.yml`)

**(a) 두 잡 모두** PyInstaller 명령에 추가:
```
--exclude-module PIL._avif --exclude-module PIL._webp `
```

**(b) `build-full` 잡** PyInstaller 명령에 추가:
```
--exclude-module torch._dynamo --exclude-module torch._inductor --exclude-module torch.onnx `
--exclude-module sympy --exclude-module mpmath --exclude-module networkx `
--exclude-module hf_xet `
```

**(c) `build-full` 잡, "Prefetch Demucs weights" 스텝 뒤**에 정리 스텝 추가. 오프라인 로드는 `refs/main` → `snapshots/<rev>/<file>` 만 읽으므로 blob 과 xet 캐시는 필요 없다:
```yaml
      - name: Prune duplicate weight copies (keep snapshots only)
        shell: pwsh
        env:
          HF_HOME: ${{ github.workspace }}\hf_home
          HF_HUB_OFFLINE: "1"
        run: |
          Remove-Item -Recurse -Force hf_home\xet -ErrorAction SilentlyContinue
          Remove-Item -Recurse -Force hf_home\hub\blobs -ErrorAction SilentlyContinue
          Get-ChildItem -Directory hf_home\hub -Filter "models--*" | ForEach-Object {
            Remove-Item -Recurse -Force (Join-Path $_.FullName "blobs") -ErrorAction SilentlyContinue
          }
          Get-ChildItem -Recurse -File hf_home | Measure-Object -Property Length -Sum | Select-Object Sum
          # 정리한 캐시로 실제 로드되는지 빌드 전에 먼저 확인 (실패하면 여기서 멈춤)
          python main.py --selftest
          if ($LASTEXITCODE -ne 0) { throw "selftest on pruned cache failed" }
```
(`python main.py --selftest` 는 콘솔 파이썬이라 `$LASTEXITCODE` 가 정상 동작한다. exe 는 `--noconsole` 이라 기존처럼 `Start-Process -Wait -PassThru` 를 써야 한다.)

**(d) `build-full` 잡, PyInstaller 스텝 뒤·selftest 앞**에:
```yaml
      - name: Prune unused torch tools
        shell: pwsh
        run: Remove-Item -Recurse -Force dist\splitwave-full\_internal\torch\bin -ErrorAction SilentlyContinue
```

**(e) Zip 스텝**을 7-Zip 최대 압축으로 교체 (windows-latest 에 `7z` 기본 설치):
```yaml
      - name: Zip
        shell: pwsh
        run: 7z a -tzip -mx=9 splitwave-full.zip .\dist\splitwave-full
```
zip 안의 최상위 폴더 이름이 기존과 같이 `splitwave-full` 인지 확인할 것 (`7z l splitwave-full.zip | Select-Object -First 30`).

**(f) 두 잡 마지막(업로드 직전)**에 크기 출력 스텝:
```yaml
      - name: Report size
        shell: pwsh
        run: Get-Item dist\splitwave.exe | Select-Object Name, Length      # lite
      # full: Get-Item splitwave-full.zip | Select-Object Name, Length
```

### 1-3. 검증·커밋

1. `pytest -q` 전체 통과 (29개 + 변경분).
2. 커밋: `build: prune duplicate weights, exclude unused modules, real separation in selftest`
3. `git push -u origin size-opt` → `gh workflow run build-windows.yml --ref size-opt` → 완료까지 대기 (`gh run watch`). 두 잡 모두 초록이어야 한다. 실패 시 `--log-failed` 로 원인을 보고 고친다. 특히 selftest 가 `ModuleNotFoundError` 로 죽으면 그 모듈을 제외 목록에서 빼고 보고서에 적는다.
4. 보고서 `.superpowers/sdd/2026-09-25-size-opt/task-1-report.md` 에: 커밋 해시, CI run URL, 라이트 exe 바이트 수, 풀 zip 바이트 수, 제외 목록에서 되돌린 것이 있으면 무엇과 이유.

---

## Task 2: 오디오 전용 ffmpeg 를 CI 에서 직접 빌드

**모델:** opus. **파일:** 새 `tools/ffmpeg/build.sh`, `tools/ffmpeg/smoke.sh`, `.github/workflows/build-windows.yml`(잡 추가·다운로드 교체), `.gitignore`(`tools/ffmpeg/out/`, `tools/ffmpeg/src/`).

**왜:** 지금 번들되는 BtbN gpl 빌드는 x264/x265/AV1 등 영상 코덱까지 든 159MB 짜리인데 앱은 오디오만 다룬다. 오디오 디코더·모든 네이티브 컨테이너·필요한 인코더만 켜서 정적 빌드하면 5~8MB 다. 앱에서 쓸 수 있는 입력 범위는 그대로여야 하므로 **오디오 디코더와 (de)muxer 는 전부** 켠다. 영상 디코더·swscale·avdevice 만 뺀다.

### 2-1. 앱이 ffmpeg 에 요구하는 것 (이게 스모크 테스트 매트릭스다)

- `common.py` `CODEC_BY_EXT`: 인코더 `libmp3lame`(320k), `aac`(256k), `pcm_s16le`, `libopus`(192k, .opus/.webm/.ogg), `flac`
- `common.py` `pitch_filter()`: `asetrate` + `aresample` + `atempo` 필터 체인 (정확한 문자열은 `python -c "from common import pitch_filter; print(pitch_filter(2))"` 로 뽑아 테스트에 쓴다)
- `separator.py` `decode_with_ffmpeg`: `-i <아무 오디오> -vn -f f32le -ac 2 -ar 44100 -` (stdout 파이프)
- `separator.py` `_reencode`: 키 조정된 스템 wav → mp3/wav
- yt-dlp `FFmpegExtractAudio` (mp3 320 / wav): 입력은 유튜브 DASH m4a(aac) 또는 webm(opus). 같은 코덱이면 `-c copy` 리먹스, 아니면 트랜스코드. HLS 를 탔을 때의 `FFmpegFixupM3u8`: `-i x.ts -c copy -f mp4 -bsf:a aac_adtstoasc` (mpegts demuxer + aac parser 필요). `FFmpegFixupM4a`: `-c copy -f mp4`.
- ffmpeg 는 `-ar/-ac` 변환 시 `aresample`, `aformat`, `abuffer`, `abuffersink`, `anull` 필터를 자동 삽입한다 → 반드시 켠다.
- 라이브 스트림 등에서 yt-dlp 가 ffmpeg 에 URL 을 넘길 수 있으므로 `http/https/tcp/tls` 프로토콜은 켜는 것을 시도한다 (Windows: `--enable-schannel`). 정적 링크가 안 되면 빼고 보고서에 적는다.

### 2-2. `tools/ffmpeg/build.sh` 설계

- 입력: 환경변수 `FFMPEG_VERSION`(기본값 최신 릴리스 — 예: 7.1.1; 실제 최신을 https://ffmpeg.org/download.html 에서 확인해 고정), `FFMPEG_SHA256`(ffmpeg.org 의 `.tar.xz.sha256` 값을 스크립트에 상수로 박는다). `OUT_DIR` 기본 `tools/ffmpeg/out`.
- 소스 `curl -L` 로 받아 sha256 검증 후 `tools/ffmpeg/src/` 에 풀기.
- 컴포넌트 목록은 소스에서 생성한다 (수작업 목록은 버전마다 어긋난다):
  - 오디오 디코더: `libavcodec/allcodecs.c` 에서 `/* audio codecs */` 부터 `/* subtitles */` 직전까지의 `ff_<name>_decoder` 이름 (PCM/DPCM/ADPCM 구간 포함). `/* external libraries */` 구간 것은 제외.
  - demuxer/muxer: `libavformat/allformats.c` 의 `ff_<name>_demuxer` / `ff_<name>_muxer` 전부, 단 external libraries 구간(libgme, libmodplug, libopenmpt, chromaprint 등) 제외.
  - 인코더: `libmp3lame aac libopus flac alac pcm_*` (와일드카드는 configure 의 `--enable-encoder='pcm_*'` 가 셸 글롭으로 처리한다), 테스트용 `pcm_f32le` 포함됨.
  - parser: `--enable-parser='*'`, bsf: `--enable-bsf='*'`.
  - 필터: `aresample aformat anull abuffer abuffersink asetrate atempo volume apad atrim asetpts aselect anullsrc amix amerge pan channelmap channelsplit join concat afade adelay silencedetect` (외부 라이브러리가 필요한 필터는 넣지 않는다).
  - 프로토콜: `file pipe data concat tcp http https tls crypto hls`.
- configure 뼈대:
  ```
  ./configure --prefix="$PREFIX" \
    --disable-everything --disable-doc --disable-ffplay --disable-ffprobe --disable-debug \
    --disable-autodetect --disable-avdevice --disable-swscale --disable-postproc \
    --enable-static --disable-shared --pkg-config-flags=--static \
    --enable-libmp3lame --enable-libopus \
    $TLS_FLAGS $PLATFORM_LDFLAGS \
    --enable-protocol=... --enable-demuxer=... --enable-muxer=... \
    --enable-decoder=... --enable-encoder=... --enable-parser='*' --enable-bsf='*' --enable-filter=...
  ```
  - MSYS2(MINGW64): `TLS_FLAGS=--enable-schannel`, `PLATFORM_LDFLAGS=--extra-ldflags=-static` (libwinpthread/libgcc 까지 정적으로. 결과 exe 는 시스템 DLL 외에 의존이 없어야 한다: `objdump -p ffmpeg.exe | grep "DLL Name"`).
  - macOS(로컬 검증용): `TLS_FLAGS=--enable-securetransport` 또는 비움. 정적 ldflags 없음.
  - `--disable-swscale` 로 ffmpeg CLI 가 안 잡히면(configure 가 swscale 요구) 그것만 되돌린다.
- `make -j$(nproc)` 후 `ffmpeg`/`ffmpeg.exe` 를 `$OUT_DIR` 로 복사. `strip` 적용.
- configure 가 "requested, but not all dependencies are satisfied" 로 죽으면 그 컴포넌트를 목록에서 빼는 필터를 스크립트에 넣는다 (예: 외부 lib 의존 항목).

### 2-3. `tools/ffmpeg/smoke.sh <ffmpeg>` — 앱 명령 전부를 실제로 실행

`python3` 로 3초 스테레오 44.1kHz 테스트 wav 생성(`wave` 모듈, 두 채널 다른 주파수 사인). 각 명령은 실패 시 즉시 `exit 1` 하고 한 줄로 어떤 단계인지 출력:

1. `ffmpeg -version` (exit 0, 출력에 `--enable-libmp3lame` 와 `--enable-libopus` 포함)
2. wav → mp3 (`-c:a libmp3lame -b:a 320k`), → m4a (`-c:a aac -b:a 256k`), → opus (`-c:a libopus -b:a 192k`), → ogg (libopus), → webm (libopus), → flac, → wav (`pcm_s16le`)
3. 키 조정: `-af "<pitch_filter(2) 문자열>"` 로 wav → mp3 (출력 길이가 원본과 ±2% 이내인지 `-f null -` 디코드해 확인하거나, python 으로 mp3 길이는 어렵다면 wav 출력으로 샘플 수 검사)
4. 디코드: m4a·opus·mp3·flac 각각 `-i x -vn -f f32le -ac 2 -ar 44100 -` 를 stdout 으로 받아 바이트 수가 `3*44100*2*4` 의 ±3% 안인지 확인 (`wc -c`)
5. yt-dlp 흉내: opus → mp3 (`-vn -acodec libmp3lame`), m4a → m4a (`-c copy -f mp4`), m4a → ts (`-c copy -f mpegts`) → `-i x.ts -c copy -f mp4 -bsf:a aac_adtstoasc out.m4a`
6. 만든 파일 전부 `-i f -f null -` 로 디코드 성공
7. 크기 출력 (`stat`/`wc -c`), 상한 검사: 15MB 초과면 실패 (영상 코덱이 딸려 들어온 신호)

### 2-4. 워크플로

`build-windows.yml` 에 잡 `build-ffmpeg` 추가, `build-lite`/`build-full` 은 `needs: build-ffmpeg` 로 바꾸고 BtbN 다운로드 스텝을 아티팩트 다운로드로 교체.

```yaml
  build-ffmpeg:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/cache@v4
        id: cache
        with:
          path: tools/ffmpeg/out/ffmpeg.exe
          key: ffmpeg-audio-${{ hashFiles('tools/ffmpeg/build.sh') }}
      - uses: msys2/setup-msys2@v2
        if: steps.cache.outputs.cache-hit != 'true'
        with:
          msystem: MINGW64
          update: false
          install: >-
            make diffutils pkgconf
            mingw-w64-x86_64-gcc mingw-w64-x86_64-nasm mingw-w64-x86_64-pkgconf
            mingw-w64-x86_64-lame mingw-w64-x86_64-opus
      - name: Build audio-only ffmpeg
        if: steps.cache.outputs.cache-hit != 'true'
        shell: msys2 {0}
        run: bash tools/ffmpeg/build.sh
      - uses: msys2/setup-msys2@v2      # 스모크 테스트도 msys2 bash 로 (캐시 히트 때도 필요)
        with: { msystem: MINGW64, update: false, install: "python mingw-w64-x86_64-binutils" }
      - name: Smoke test + dependency check
        shell: msys2 {0}
        run: |
          bash tools/ffmpeg/smoke.sh tools/ffmpeg/out/ffmpeg.exe
          objdump -p tools/ffmpeg/out/ffmpeg.exe | grep "DLL Name"
      - uses: actions/upload-artifact@v4
        with: { name: ffmpeg-audio, path: tools/ffmpeg/out/ffmpeg.exe, if-no-files-found: error }
```
(setup-msys2 를 두 번 쓰는 게 지저분하면 한 번만 쓰고 build 스텝 안에서 캐시 히트 여부를 `if [ -f ... ]` 로 분기해도 된다. MSYS2 의 `python` 패키지 이름·binutils 이름은 실제로 확인해서 쓴다.)

lite/full 잡의 다운로드 스텝 교체:
```yaml
      - uses: actions/download-artifact@v4
        with: { name: ffmpeg-audio, path: . }
      - name: Report ffmpeg size
        shell: pwsh
        run: Get-Item ffmpeg.exe | Select-Object Name, Length
```

### 2-5. 순서·검증

1. **먼저 맥에서** `bash tools/ffmpeg/build.sh` 로 configure 옵션을 검증한다 (`brew install lame opus nasm pkg-config` 필요하면 설치). 그 다음 `bash tools/ffmpeg/smoke.sh tools/ffmpeg/out/ffmpeg` 통과. 여기서 컴포넌트 목록·필터 오류를 다 잡고 CI 로 간다 (CI 한 바퀴가 10분이라 로컬이 훨씬 싸다).
2. 커밋: `build: audio-only ffmpeg built from source in CI` → push → `gh workflow run build-windows.yml --ref size-opt` → 세 잡 초록까지 반복. 첫 빌드는 캐시 미스라 10~15분.
3. 두 번째 dispatch 에서 `build-ffmpeg` 가 캐시 히트로 빨리 끝나는지 확인.
4. 보고서 `.superpowers/sdd/2026-09-25-size-opt/task-2-report.md`: 커밋, CI run URL, `ffmpeg.exe` 바이트 수, 라이트 exe·풀 zip 바이트 수, 켜지 못한 것(예: https)이 있으면 무엇과 이유, ffmpeg 버전.

---

## Task 3 (컨트롤러): README 갱신, 산출물 내려받기, 사용자 확인

README 의 용량 표(15행), "ffmpeg 번들" 설명(90~91행), 빌드 절차 안내를 새 수치·구조로 갱신. `gh run download` 로 `dist/ci/` 갱신, `SHA256SUMS.txt` 재생성. main 머지·push·릴리스는 사용자에게 수치를 보여주고 결정을 받는다.

## 전역 제약

- 이모지 금지, UI 문구·앱 동작 변경 금지 (selftest 제외).
- 서브에이전트·리뷰어 띄우지 않는다. 검증은 pytest + CI 초록으로 갈음.
- `main` 에 push 하지 않는다. `size-opt` 브랜치만.
- 보고서는 파일로, 대화 응답은 상태·커밋·한 줄 요약만.
