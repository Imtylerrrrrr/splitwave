"""시제품 트래커: 스펙트럼 영역 자기 출력 상쇄 + 좁은 사전. 실제 스템 폐루프로 평가."""
import sys, os, math
import numpy as np
sys.path.insert(0, "/Users/tylerrr/Documents/GitHub/splitwave")
from tempofollow.stretch import WSOLA
from tempofollow.engine import decode, SR, HOP, SLEW_PER_S
from tempofollow import tempo as T
from common import find_ffmpeg

def est_delay(m, r, mx, sr, lo_lag_s=0.005):
    w = np.hanning(len(m)); n = 1 << (len(m) + len(r) - 1).bit_length()
    Rr = np.fft.rfft(m * w, n) * np.conj(np.fft.rfft(r * w, n))
    f = np.fft.rfftfreq(n, 1 / sr)
    Rm = np.where((f >= 100) & (f <= 8000), Rr / (np.abs(Rr) + 1e-12), 0)
    c = np.fft.irfft(Rm, n)[:mx + 1]; lo = int(lo_lag_s * sr)
    k = lo + int(np.argmax(c[lo:]))
    return k, float(c[k] / (np.sqrt(np.mean(c ** 2)) + 1e-12))

class Tracker2:
    def __init__(self, sr, base, hop=256, n_fft=1024, ratio_range=(0.7, 1.3), window_s=4.0, update_s=0.25,
                 tau_s=1.0, prior_sigma=0.1, min_crest=2.5, min_conf=0.2, deadband=0.005,
                 beta=2.0, tail=0.9, lam=0.999, max_delay_s=0.5, cancel=True, agc=True, floor=0.003, min_frac=0.25):
        self.sr, self.hop, self.n_fft, self.base = sr, hop, n_fft, base
        self.lo, self.hi = base * ratio_range[0], base * ratio_range[1]
        self.prior_sigma, self.min_crest, self.min_conf, self.deadband = prior_sigma, min_crest, min_conf, deadband
        self.beta, self.tail, self.lam, self.cancel = beta, tail, lam, cancel
        self.alpha = 1 - math.exp(-update_s / tau_s)
        self.W = round(window_s * sr / hop); self.upd = round(update_s * sr / hop)
        self.ring = np.zeros(self.W); self.frames = 0; self.since = 0
        self.keep = int((max_delay_s + 2.5) * sr)
        self.mb = np.zeros(self.keep, np.float32); self.rb = np.zeros(self.keep, np.float32)
        self.pending = 0
        self.win = np.hanning(n_fft); nb = n_fft // 2 + 1
        self.prevS = np.zeros(nb); self.Re = np.zeros(nb)
        self.mm = np.zeros(nb); self.mr = np.zeros(nb); self.cov = np.zeros(nb); self.var = np.zeros(nb)
        self.max_delay = int(max_delay_s * sr); self.delays = []; self.delay = None; self.gcc_since = 0
        self.bpm = float(base); self.confidence = 0.0; self.measurements = 0; self.playback_bpm = None
        self.resid = 0.0
        self.agc, self.floor, self.min_frac = agc, floor, min_frac
        self.scale = floor; self.raw_ring = np.zeros(self.W); self.prevRaw = np.zeros(nb); self.frac = 1.0
    def process(self, mic, ref):
        n = len(mic)
        self.mb = np.concatenate([self.mb[n:], mic]); self.rb = np.concatenate([self.rb[n:], ref])
        self.pending += n
        while self.pending >= self.hop:
            self.pending -= self.hop
            self._frame(self.pending)   # 프레임 끝이 버퍼 끝에서 pending 샘플 앞
    def _frame(self, back):
        end = len(self.mb) - back
        Mm = np.abs(np.fft.rfft(self.mb[end - self.n_fft:end] * self.win))
        if self.cancel and self.delay is not None:
            e2 = end - self.delay
            Mr = np.abs(np.fft.rfft(self.rb[e2 - self.n_fft:e2] * self.win))
            self.Re = np.maximum(Mr, self.tail * self.Re)
            l = self.lam
            self.mm = l * self.mm + (1 - l) * Mm; self.mr = l * self.mr + (1 - l) * self.Re
            self.cov = l * self.cov + (1 - l) * (Mm - self.mm) * (self.Re - self.mr)
            self.var = l * self.var + (1 - l) * (self.Re - self.mr) ** 2
            G = np.clip(self.cov / (self.var + 1e-12), 0, None)
            Mc = np.maximum(Mm - self.beta * G * self.Re, 0)
            self.resid = float(Mc.sum() / (Mm.sum() + 1e-12))
        else:
            Mc = Mm
        if self.agc:
            rms = float(np.sqrt(np.mean(self.mb[end - self.n_fft:end] ** 2)))
            self.scale = max(self.scale * 0.9995, rms, self.floor)
            S = np.log1p(Mc / self.scale); Sr = np.log1p(Mm / self.scale)
        else:
            S = np.log1p(100 * Mc); Sr = np.log1p(100 * Mm)
        v = np.maximum(S - self.prevS, 0).sum(); self.prevS = S
        vr = np.maximum(Sr - self.prevRaw, 0).sum(); self.prevRaw = Sr
        self.ring[:-1] = self.ring[1:]; self.ring[-1] = v
        self.raw_ring[:-1] = self.raw_ring[1:]; self.raw_ring[-1] = vr
        self.frames += 1; self.since += 1; self.gcc_since += 1
        if self.cancel and self.gcc_since >= round(1.0 * self.sr / self.hop):
            self.gcc_since = 0
            m = self.mb[end - 2 * self.sr:end]; r = self.rb[end - 2 * self.sr:end]
            if np.abs(r).max() > 1e-6:
                k, conf = est_delay(m, r, self.max_delay, self.sr)
                if conf >= 6.0:
                    self.delays = (self.delays + [k])[-9:]; self.delay = int(np.median(self.delays))
        if self.since >= self.upd:
            self.since = 0; self._measure()
    def _measure(self):
        if self.frames < self.W: return
        o = self.ring.copy()
        self.frac = float(o.sum() / (self.raw_ring.sum() + 1e-12))
        if self.frac < self.min_frac: return
        if o.max() <= 1e-9 or o.max() / (o.mean() + 1e-12) < self.min_crest: return
        res = T._acf_peak_bpm(o, self.sr, self.hop, self.lo, self.hi, self.bpm, self.prior_sigma)
        if res is None or res[1] < self.min_conf: return
        bpm_meas, self.confidence = res
        if self.playback_bpm and abs(bpm_meas - self.playback_bpm) < self.deadband * self.playback_bpm: return
        self.bpm += self.alpha * (bpm_meas - self.bpm); self.measurements += 1

def stretch_const(x, r, n):
    w = WSOLA(x); parts = []; got = 0
    while got < n:
        c = w.next_chunk(r)
        if c is None: break
        parts.append(c); got += len(c)
    y = np.concatenate(parts).mean(axis=1)
    return np.pad(y, (0, max(0, n - len(y))))[:n]

def reverb_ir(sr, t60=0.4, direct=1.0, wet=0.35, seed=3):
    rng = np.random.default_rng(seed); n = int(t60 * sr)
    ir = rng.normal(0, 1, n) * np.exp(-6.9 * np.arange(n) / n); ir *= wet / np.sqrt((ir ** 2).sum()); ir[0] += direct
    return ir.astype(np.float32)

def run(stems, play_names, start, secs, drum_r, band, bleed_gain, reverb, live_stems=None, **kw):
    ff = find_ffmpeg(); ext = os.path.splitext(os.listdir(stems)[0])[1]
    L = lambda n: decode(os.path.join(stems, n + ext), ff)[int(start * SR):]
    play = sum(L(n) for n in play_names)
    drums = L("드럼")
    base = T.estimate_bpm(decode(os.path.join(stems, "드럼" + ext), ff)[:90 * SR].mean(axis=1), SR)
    n = int(secs * SR) + HOP
    live = np.zeros(n, np.float32)
    if drum_r is not None:
        lext = os.path.splitext(os.listdir(live_stems)[0])[1]
        LL = lambda nm: decode(os.path.join(live_stems, nm + lext), ff)[int(start * SR):]
        base_b = T.estimate_bpm(decode(os.path.join(live_stems, "드럼" + lext), ff)[:90 * SR].mean(axis=1), SR)
        r_live = base * drum_r / base_b
        live += stretch_const(LL("드럼"), r_live, n)
        for b in band: live += stretch_const(LL(b), r_live, n)
    tr = Tracker2(SR, base, **kw)
    w = WSOLA(play); ratio = 1.0; delay = int(0.12 * SR)
    ir = reverb_ir(SR) if reverb else None
    hist = np.zeros(delay + (len(ir) if reverb else 1) + HOP, np.float32)
    dt = HOP / SR; t = 0; rows = []; nxt = 0.0
    while t < secs * SR:
        target = float(np.clip(tr.bpm / base, 0.7, 1.3))
        ratio += float(np.clip(target - ratio, -SLEW_PER_S * dt, SLEW_PER_S * dt))
        tr.playback_bpm = base * ratio
        out = w.next_chunk(ratio)
        if out is None: break
        mono = out.mean(axis=1)
        hist = np.concatenate([hist[HOP:], mono])
        if reverb:
            seg = hist[len(hist) - HOP - delay - len(ir) + 1: len(hist) - delay]
            bleed = np.convolve(seg, ir, mode="valid")[-HOP:]
        else:
            bleed = hist[len(hist) - HOP - delay: len(hist) - delay]
        mic = (bleed_gain * bleed + live[t:t + HOP]).astype(np.float32)
        tr.process(mic, mono.astype(np.float32))
        t += HOP
        if t / SR >= nxt:
            rows.append((t / SR, ratio, tr.bpm, tr.confidence, tr.measurements, tr.delay, tr.resid)); nxt += 15
    rr = [r[1] for r in rows]
    tgt = drum_r if drum_r is not None else 1.0
    tail_r = [r[1] for r in rows if r[0] >= 30]
    err = max(abs(x - tgt) for x in tail_r) if tail_r else float("nan")
    return base, rows, ratio, err

if __name__ == "__main__":
    stems, live_stems = sys.argv[1], sys.argv[2]; play = sys.argv[3].split("+"); reverb = sys.argv[4] == "reverb"; start = float(sys.argv[5])
    cfgs = {"E frac0.25 b2": dict(prior_sigma=0.1, min_conf=0.2),
            "F frac0.40 b2": dict(prior_sigma=0.1, min_conf=0.2, min_frac=0.4)}
    scen = {"S1 블리드만": dict(drum_r=None, band=[]),
            "S2 드러머0.95": dict(drum_r=0.95, band=[]),
            "S3 드러머1.05": dict(drum_r=1.05, band=[]),
            "S4 드러머0.95+밴드": dict(drum_r=0.95, band=["기타", "베이스", "보컬"]),
            "S5 드러머1.08+밴드": dict(drum_r=1.08, band=["기타", "베이스", "보컬"])}
    print(f"재생 {play}, reverb={reverb}")
    for cn, kw in cfgs.items():
        for sn, sc in scen.items():
            base, rows, ratio, err = run(stems, play, start, 90, bleed_gain=float(os.environ.get('BLEED', '1.0')), reverb=reverb, live_stems=live_stems, **sc, **kw)
            tl = " ".join(f"{r[1]:.3f}" for r in rows)
            print(f"{cn:14s} {sn:16s} 최종 {ratio:.3f} | 30s후 최대오차 {err*100:4.1f}% | 측정 {rows[-1][4]:3d} | 지연 {rows[-1][5]} | {tl}")
