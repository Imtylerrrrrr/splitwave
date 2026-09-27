# 템포 추종 재생(tempofollow) 설계 + 구현 계획 (2026-09-27)

## 목표

드러머가 치는 박자를 마이크로 받아 **실시간으로 템포(BPM)를 추정**하고, 곡을 그 템포에 맞춰
**음높이는 그대로 두고 속도만 바꿔** 재생하는 독립 앱. splitwave 본체에 통합하기 전 단계의 사이드 앱이며,
같은 레포 안에 `tempofollow/` 패키지로 둔다. (`python -m tempofollow`)

사용 시나리오: splitwave로 스템을 분리해 드럼을 뺀 곡을 틀어 놓고, 드러머가 자기 템포로 치면 곡이 따라온다.

## 사용자가 정한 것

- 마이크로 드럼 박자를 받아서 BPM을 유동적으로 바꿔 재생.
- 입력으로 곡의 **기본 BPM**을 받는다.
- 본체 통합 전이므로 **별도 앱**.
- 나머지는 설계자 재량 ("나머지는 알아서 만들어줘").

## 설계자가 정한 것

| 항목 | 결정 | 이유 |
|---|---|---|
| 템포 추정 | 마이크 → 스펙트럼 플럭스 온셋 강도 → 4초 창 자기상관(ACF) 최대 lag → BPM. 이산 온셋 검출·임계값 없음 | 8분·16분 잔타를 자동으로 흡수, 튜닝 파라미터 최소 |
| 탐색 범위 | 기본 BPM × [1−r, 1+r], r 기본 30 % | 2배·1/2배 오류를 구조적으로 배제 |
| 위상(박 위치) 동기 | 안 함. 템포만 맞춘다 | 요청 범위. 드러머가 곡을 들으며 맞춘다 |
| 타임스트레치 | WSOLA (numpy 자체 구현), 프레임 2048·합성 hop 1024·탐색 ±512 | 실시간 스트리밍 가능, 외부 의존성 없음, 드럼 없는 반주에 충분한 품질 |
| 오디오 I/O | `sounddevice` (PortAudio) 입력/출력 스트림 분리 | pip 휠에 PortAudio 포함, Win/mac 동일 코드 |
| 디코딩 | 기존 `common.find_ffmpeg()` + `ffmpeg -f f32le -ac 2 -ar 44100` | 본체와 같은 포맷 지원(mp3/m4a/wav …) |
| 재생 시작 | "첫 타격에 맞춰 시작" 체크박스(기본 켬): 마이크 피크가 임계값(dBFS)을 넘으면 재생 시작 | 드러머가 시작 버튼을 누르고 자리로 갈 시간이 필요 |
| 드러머가 멈추면 | 마지막 템포를 유지 | 갑자기 기본 템포로 튀는 것보다 자연스러움 |
| GUI | customtkinter, 본체와 같은 테마·아이콘, 이모지 금지 | 통합 대비 |
| 테스트 | numpy만 쓰는 `tempo.py`·`stretch.py`를 합성 신호로 검증. 오디오 장치·GUI는 사람이 확인 | CI(Windows, numpy 있음)에서 돌아감. sounddevice는 테스트에서 import 금지 |

트레이드오프(사용자에게 알릴 것): 마이크가 스피커 소리를 같이 받으면 곡 자체의 박이 추정에 섞여 현재 템포에
관성이 생긴다. 헤드폰/인이어 모니터를 권장. 템포 변화 반영은 창 4초 + 평활 때문에 약 2~4초 걸린다.

## 파일 구조

```
tempofollow/
  __init__.py      # 비움 (sounddevice import 금지: 테스트가 tempo/stretch만 import)
  __main__.py      # from tempofollow.app import main; main()
  tempo.py         # OnsetStrength, TempoTracker(스트리밍), estimate_bpm(오프라인). numpy만
  stretch.py       # WSOLA 스트리밍 스트레처. numpy만
  engine.py        # ffmpeg 디코드, 장치 목록, 입력/출력 스트림, 제어 루프(비율 슬루), 상태
  app.py           # customtkinter GUI
tests/test_tempofollow_tempo.py
tests/test_tempofollow_stretch.py
requirements-tempofollow.txt   # -r requirements.txt / numpy / sounddevice>=0.5
```

`tests/test_no_emoji.py`의 parametrize 목록에 `tempofollow/app.py`, `tempofollow/engine.py` 추가.

---

## tempo.py

### OnsetStrength(sr, n_fft=1024, hop=256)

- 내부 버퍼 `_buf`(길이 n_fft, 0으로 초기화)와 미처리 샘플 큐. `process(mono: np.ndarray) -> np.ndarray`는
  hop 샘플이 모일 때마다 프레임 하나를 만들고, 만들어진 프레임들의 온셋 강도 배열을 돌려준다 (0개일 수 있음).
- 프레임: `_buf = concat(_buf[hop:], block)` → `x = _buf * hann(n_fft)` (`np.hanning`) → `mag = |rfft(x)|`
  → `S = log1p(100 * mag)` → `flux = sum(max(S - S_prev, 0))` → `S_prev = S`. 첫 프레임은 S_prev = 0.
- `hop_seconds = hop / sr`.

### TempoTracker(sr, base_bpm, hop=256, ratio_range=(0.7, 1.4), window_s=4.0, update_s=0.25, tau_s=1.0, prior_sigma_oct=0.3, min_crest=2.5, min_confidence=0.1)

- `OnsetStrength(sr, hop=hop)`를 안에 둔다. 온셋 강도 링 버퍼 `W = round(window_s * sr / hop)` 프레임(0 초기화).
- `process(mono)`: 온셋 강도 프레임들을 링에 넣고, `update_s`에 해당하는 프레임 수(`round(update_s*sr/hop)`)가
  쌓일 때마다 `_measure()`.
- `_measure()`:
  1. `o = ring (시간순)`. `o.max() <= 1e-9`면 return (무음).
  2. `crest = o.max() / (o.mean() + 1e-12)`. `crest < min_crest`면 return (정상 잡음·지속음: 드럼 아님).
  3. 평활: `o = np.convolve(o, hann7 / hann7.sum(), mode="same")` (`hann7 = np.hanning(7)`). 지터 허용.
  4. `x = o - o.mean()`; `r = irfft(|rfft(x, 2W)|^2)[:W]`; `r[0] <= 0`이면 return; `r = r / r[0]`.
  5. lag ↔ BPM: `bpm(l) = 60 * sr / (l * hop)`. `lag_min = ceil(60*sr/(base*hi*hop))`, `lag_max = floor(60*sr/(base*lo*hop))`,
     `lag_max = min(lag_max, W // 2)`. `lag_min < 2`면 2. `lag_min >= lag_max`면 return.
  6. 사전 가중치: `w(l) = exp(-0.5 * (log2(bpm(l) / self.bpm) / prior_sigma_oct)^2)`. `score = r[l] * w(l)`, `l ∈ [lag_min, lag_max]`.
  7. `l* = argmax score`. `r[l*] < min_confidence`면 return.
  8. 포물선 보간 (l*가 양 끝이 아닐 때): `a, b, c = score[l*-1], score[l*], score[l*+1]`;
     `denom = a - 2b + c`; `delta = 0 if denom == 0 else clip(0.5*(a - c)/denom, -0.5, 0.5)`; `lag = l* + delta`.
  9. `bpm_meas = 60*sr/(lag*hop)`; 범위 `[base*lo, base*hi]`로 clip.
     `alpha = 1 - exp(-update_s / tau_s)`; `self.bpm += alpha * (bpm_meas - self.bpm)`; `self.confidence = r[l*]`; `self.measurements += 1`.
- 공개 속성: `bpm`(초기값 base_bpm, 측정이 채택될 때만 변함 → 드러머가 멈추면 자동 유지), `confidence`(초기 0.0), `measurements`(채택 횟수).

### estimate_bpm(mono, sr, lo=60.0, hi=200.0, prior_bpm=110.0, prior_sigma_oct=0.6) -> float

오프라인. 전체 신호의 온셋 강도(OnsetStrength, hop 256) → 위 3~8단계와 같은 계산을 창 전체로 한 번 수행
(사전 중심은 `prior_bpm`, crest·confidence 검사 없음). 온셋 강도가 전부 0이면 `ValueError("no onsets")`.
TempoTracker와 코드를 공유할 것: `_acf_peak_bpm(o, sr, hop, bpm_lo, bpm_hi, prior_bpm, prior_sigma_oct) -> (bpm, confidence) | None` 같은 모듈 함수 하나로 3~8단계를 빼고 둘 다 그걸 부른다.

### 테스트 tests/test_tempofollow_tempo.py (numpy만, `pytest.importorskip("numpy")`)

`clicks(bpm, seconds, sr)`: 각 박마다 5 ms 길이의 감쇠 노이즈 버스트(진폭 0.8, `np.random.default_rng(0)`)를 놓은 mono float32.

1. `test_estimate_bpm_click_track`: `estimate_bpm(clicks(100, 20, 44100), 44100)` → `abs(bpm - 100) < 1.0`.
2. `test_tracker_converges_and_follows`: `t = TempoTracker(48000, base_bpm=110)`. `clicks(100, 6, 48000)`을 480샘플씩 `process` →
   `abs(t.bpm - 100) < 2`. 이어서 `clicks(120, 8, 48000)` → `abs(t.bpm - 120) < 2.4`.
3. `test_tracker_holds_on_silence`: 2번처럼 100으로 수렴시킨 뒤 `np.zeros(48000*5)` → bpm 변화 없음 (`==` 비교).
4. `test_tracker_ignores_noise`: 새 트래커(base 110)에 `rng.normal(0, 0.1, 48000*6)` → `t.measurements == 0`, `t.bpm == 110`.
5. `test_estimate_bpm_rejects_silence`: `estimate_bpm(np.zeros(44100*5), 44100)` → `ValueError`.

---

## stretch.py

### WSOLA(audio: np.ndarray[(n, ch) float32], frame=2048, hop=1024, tol=512)

- `len(audio) < frame`이면 `ValueError`. `mono = audio.mean(axis=1)`, `win = np.hanning(frame + 1)[:-1]` (periodic Hann → 50 % 겹침 합이 1).
- 상태: `in_pos: float = 0.0`(명목 분석 위치), `prev: int | None = None`(마지막으로 고른 프레임 시작), `tail = zeros((hop, ch))`, `done = False`, `flushed = False`.
- `next_chunk(ratio: float) -> np.ndarray[(hop, ch)] | None`. `ratio` = 재생 속도 배율(1.2 = 20 % 빠르게). 호출마다 hop 샘플을 낸다.
  1. `done`이면: `flushed`가 아니면 `flushed = True; return tail` (마지막 겹침 꼬리), 이미 flush했으면 `None`.
  2. `prev is None`(첫 프레임): `p = 0`.
     아니면: `in_pos += hop * ratio`; `center = round(in_pos)`; `lo = max(0, center - tol)`; `hi = min(len - frame, center + tol)`;
     `ref_start = prev + hop`; `ref_start + frame > len` 또는 `lo > hi`이면 `done = True`로 두고 1번 처리(꼬리 반환).
     `ref = mono[ref_start : ref_start + frame]`(자연스러운 연속 구간); `seg = mono[lo : hi + frame]`;
     정규화 상호상관: `L = len(seg)`, `n = 다음 2의 거듭제곱 >= L`,
     `c = irfft(rfft(seg, n) * conj(rfft(ref, n)), n)[: hi - lo + 1]`;
     후보 에너지 `e[k] = sum(seg[k:k+frame]^2)`는 `cumsum(seg^2)`로; `score = c / sqrt(e + 1e-9)`; `p = lo + argmax(score)`.
  3. `fr = audio[p : p + frame] * win[:, None]`; `out = tail + fr[:hop]`; `tail = fr[hop:].copy()`; `prev = p`; `return out`.
- `position_samples` 속성: `prev + hop` (대략적 현재 입력 위치, UI 표시용). `finished` 속성 = `done and flushed`.

### 테스트 tests/test_tempofollow_stretch.py

`signal(seconds, sr=44100)`: 440 Hz 사인(진폭 0.5) + `rng.normal(0, 0.05)` 잡음, 스테레오(두 채널 동일).
`run(w, ratio_fn)`: `next_chunk`를 None까지 호출해 이어붙임. `ratio_fn(i)`로 호출 회차별 비율.

1. `test_identity_at_ratio_one`: ratio 1.0 → 출력 `y`, 입력 `x`; `y[hop : len(y)-hop]`와 `x[hop : ...]` 같은 길이로 맞춰 `max|y-x| < 1e-4`.
2. `test_length_scales_with_ratio`: ratio 1.5와 0.7 각각 `abs(len(y) - len(x)/ratio) < 2*frame`.
3. `test_pitch_preserved`: ratio 1.25, 0.8: 출력 mono의 rfft 최대 bin 주파수가 440 ± 2 Hz. NaN 없음.
4. `test_ratio_can_change_midstream`: `ratio_fn = lambda i: 0.8 if i % 50 < 25 else 1.3` → 예외 없이 끝나고 길이 > 0.
5. `test_short_input_rejected`: 1000샘플 → `ValueError`.

---

## engine.py

```python
SR = 44100          # 재생 샘플레이트 (디코드도 이 값)
HOP = 1024          # WSOLA hop = 출력 blocksize
AHEAD_S = 0.3       # 미리 채워 둘 출력 버퍼 길이 (비율 변화 반영 지연의 상한)
SLEW_PER_S = 0.08   # 초당 최대 비율 변화
```

- `decode(path, ffmpeg) -> np.ndarray[(n,2) float32]`: `[ffmpeg, "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", "44100", "-"]`,
  `subprocess.run(capture_output=True, creationflags=CREATE_NO_WINDOW on nt)`; returncode≠0이면 `RuntimeError(stderr 일부)`;
  `np.frombuffer(stdout, np.float32).reshape(-1, 2).copy()`.
- `list_devices() -> (inputs, outputs)`: `sd.query_devices()`에서 `max_input_channels > 0` / `max_output_channels > 0`인 `(index, name)` 목록.
  `default_devices() -> (in_idx, out_idx)` = `sd.default.device`.
- `class Engine`: `load(path)`(decode, `self.audio`, `self.duration_s`), `start(base_bpm, in_dev, out_dev, range_pct, wait_for_hit, hit_threshold_db)`, `stop()`, `status() -> dict`.
  - `start`:
    - `mic_sr = int(sd.query_devices(in_dev)["default_samplerate"])`; `tracker = TempoTracker(mic_sr, base_bpm, ratio_range=(1 - r, 1 + r))` (r = range_pct/100).
    - `stretcher = WSOLA(self.audio)`; 출력 링 버퍼 `ring = zeros((SR*2, 2))` + `lock`, `w_idx/r_idx/count`.
    - `InputStream(device=in_dev, channels=1, samplerate=mic_sr, blocksize=512, dtype="float32", callback=_in_cb)`:
      콜백은 `indata[:, 0].copy()`를 `queue.Queue(maxsize=256)`에 `put_nowait`(가득 차면 버림).
    - 분석 스레드: 큐에서 꺼내 `tracker.process(block)`; `peak_db = 20*log10(max(|block|) + 1e-9)`; `self.level_db = peak_db`;
      `wait_for_hit and not playing and peak_db > hit_threshold_db`이면 `self.playing = True`.
      `wait_for_hit`이 False면 start 직후 `playing = True`.
    - `OutputStream(device=out_dev, channels=2, samplerate=SR, blocksize=HOP, dtype="float32", callback=_out_cb)`:
      `playing`이 아니거나 링에 `frames`만큼 없으면 0 출력(`underflows += 1`은 playing일 때만), 있으면 링에서 복사.
    - 생산 스레드 루프(5 ms 간격): 링에 `AHEAD_S*SR` 미만이면 (a) 비율 갱신: `target = clip(tracker.bpm / base_bpm, 1-r, 1+r)`;
      `dt = now - last`; `step = clip(target - ratio, -SLEW_PER_S*dt, SLEW_PER_S*dt)`; `ratio += step`;
      (b) `chunk = stretcher.next_chunk(ratio)`; None이면 `finished = True`, 루프 종료; 아니면 링에 쓴다.
      `playing`이 아니면 링을 채워 두기만 하고(최초 0.3초 분) 기다린다.
    - 스트림/스레드 예외는 `self.error = str(e)`에 담고 `stop()`.
  - `stop()`: 플래그 내리고 스트림 `stop(); close()`, 스레드 join(timeout 2).
  - `status()`: `dict(bpm=tracker.bpm, confidence, ratio, playback_bpm=base*ratio, position_s=stretcher.position_samples/SR, duration_s, level_db, playing, finished, underflows, error)`.

## app.py (customtkinter)

`main.py`의 스타일을 따른다: 다크 모드, `resource_path("assets/theme.json")`, `assets/icon.png` 아이콘, `mark.png` + 제목 헤더. 창 제목 "Tempo Follow", 크기 480x600, 고정.

행 순서:
1. `곡 파일` — 경로 라벨(없으면 "선택 안 됨") + `파일 선택` 버튼(`filedialog.askopenfilename`, 오디오 확장자 필터). 선택 시 스레드에서 `engine.load`, 상태줄에 "불러오는 중…" → "길이 3:21".
2. `기본 BPM` — CTkEntry(placeholder "예: 120") + `곡에서 추정` 버튼: 스레드에서 `estimate_bpm(audio.mean(axis=1), SR)` → 엔트리에 소수 1자리로 채움. 곡 미선택이면 상태줄 안내.
3. `마이크` / `출력 장치` — CTkOptionMenu 두 개(장치 이름), 기본값은 시스템 기본 장치.
4. `추종 범위 ±` — CTkEntry(기본 "30") + "%" 라벨.
5. `첫 타격에 맞춰 시작` CTkCheckBox(기본 켬) + `타격 감도` CTkSlider(-40 ~ -6, 기본 -20) + 현재 값 라벨 "-20 dB".
6. `마이크 레벨` CTkProgressBar (level_db를 -60~0 → 0~1로).
7. 큰 숫자 3개 (font size 28 bold): `드럼 BPM` / `재생 BPM` / `속도`(예: "x1.03"), 아래 작은 라벨. 그 아래 진행 "0:42 / 3:21".
8. `시작` 버튼(누르면 `정지`로 바뀜) + 상태줄 라벨.

동작:
- 시작: 파일 없음 / BPM 파싱 실패(float, >0) / 범위 파싱 실패(1~90) → 상태줄에 이유, 시작 안 함. ffmpeg 없으면 앱 시작 시 상태줄에 README 안내.
- 시작 후 `after(100, _poll)`로 `engine.status()`를 읽어 표시. `finished`면 자동 정지 + "재생 끝". `error`면 상태줄에 표시 + 정지.
- `wait_for_hit`이고 아직 `playing`이 아니면 상태줄 "드럼을 치면 시작합니다".
- 창 닫을 때 `engine.stop()`.
- 이모지 금지. 텍스트는 한국어.

## README

"개발자용" 앞에 짧은 절 `## 사이드 앱: 템포 추종 재생 (실험)` 추가: 무엇인지 2문장, 실행법
(`pip install -r requirements-tempofollow.txt` → `python -m tempofollow`), 사용 순서 4줄, 주의 2줄(헤드폰 권장, 반영 지연 2~4초, 기본 BPM이 틀리면 못 따라감). 실행파일 배포는 아직 없음이라고 명시.

## 검증

- `pytest -q` 전체 통과 (기존 테스트 + 새 테스트 10개).
- `python -m tempofollow`가 뜨고, 파일 선택·추정·시작/정지가 예외 없이 동작 (설계자가 맥에서 확인).
- 실제 드럼 + 마이크 테스트는 사용자 몫.

## 범위 밖

- 박 위치(위상) 동기, 루프 재생, 본체 통합, Windows 실행파일 빌드.
