#!/usr/bin/env bash
# Smoke test for the audio-only ffmpeg: runs every ffmpeg command shape the app
# (common.py, separator.py) and yt-dlp's postprocessors use. Any failure prints
# one line naming the step and exits 1.
#
# Usage: bash tools/ffmpeg/smoke.sh path/to/ffmpeg[.exe]
set -u

FF="${1:?usage: smoke.sh path/to/ffmpeg}"
# Exact output of common.pitch_filter(2). Regenerate with:
#   PYTHONPATH=. python -c "from common import pitch_filter; print(pitch_filter(2))"
PITCH_FILTER="${PITCH_FILTER:-aresample=48000,asetrate=53878,aresample=48000,atempo=0.890899}"
MAX_BYTES=$((15 * 1024 * 1024))
SECONDS_LEN=3
PCM_EXPECTED=$((SECONDS_LEN * 44100 * 2 * 4))   # f32le, stereo, 44.1 kHz

if command -v python3 >/dev/null 2>&1; then PY=python3
elif command -v python >/dev/null 2>&1; then PY=python
else echo "smoke: FAIL setup: python3 not found (install python)"; exit 1; fi

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

fail() { echo "smoke: FAIL $*"; exit 1; }
ok() { echo "smoke: ok   $*"; }
ff() { "$FF" -hide_banner -loglevel error -nostdin -y "$@"; }
nbytes() { wc -c < "$1" | tr -d ' '; }
# within <actual> <expected> <percent>
within() { [ "$1" -ge $(($2 - $2 * $3 / 100)) ] && [ "$1" -le $(($2 + $2 * $3 / 100)) ]; }

# 0. test input: 3 s stereo 44.1 kHz s16 wav, 440 Hz left / 660 Hz right
"$PY" - "$T/in.wav" "$SECONDS_LEN" <<'EOF' || fail "setup: could not write test wav"
import math, struct, sys, wave
path, secs = sys.argv[1], int(sys.argv[2])
rate = 44100
frames = bytearray()
for i in range(rate * secs):
    l = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
    r = int(12000 * math.sin(2 * math.pi * 660 * i / rate))
    frames += struct.pack("<hh", l, r)
w = wave.open(path, "wb")
w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate)
w.writeframes(bytes(frames)); w.close()
EOF

# 1. version / configuration
ver="$("$FF" -hide_banner -version 2>&1)" || fail "1 version: ffmpeg -version exited non-zero"
case "$ver" in *--enable-libmp3lame*) ;; *) fail "1 version: --enable-libmp3lame missing from configuration";; esac
case "$ver" in *--enable-libopus*) ;; *) fail "1 version: --enable-libopus missing from configuration";; esac
ok "1 version: $(printf '%s\n' "$ver" | head -n 1)"

# 2. encoders used by common.CODEC_BY_EXT
ff -i "$T/in.wav" -c:a libmp3lame -b:a 320k "$T/enc.mp3"  || fail "2 encode: wav -> mp3 (libmp3lame 320k)"
ff -i "$T/in.wav" -c:a aac -b:a 256k "$T/enc.m4a"         || fail "2 encode: wav -> m4a (aac 256k)"
ff -i "$T/in.wav" -c:a libopus -b:a 192k "$T/enc.opus"    || fail "2 encode: wav -> opus (libopus 192k)"
ff -i "$T/in.wav" -c:a libopus -b:a 192k "$T/enc.ogg"     || fail "2 encode: wav -> ogg (libopus 192k)"
ff -i "$T/in.wav" -c:a libopus -b:a 192k "$T/enc.webm"    || fail "2 encode: wav -> webm (libopus 192k)"
ff -i "$T/in.wav" -c:a flac "$T/enc.flac"                 || fail "2 encode: wav -> flac"
ff -i "$T/in.wav" -c:a pcm_s16le "$T/enc.wav"             || fail "2 encode: wav -> wav (pcm_s16le)"
ok "2 encode: mp3 m4a opus ogg webm flac wav"

# 3. key shift (common.shift_pitch): filter chain must keep the duration
ff -i "$T/in.wav" -af "$PITCH_FILTER" -c:a libmp3lame -b:a 320k "$T/pitch.mp3" || fail "3 pitch: wav -> mp3 with pitch filter"
ff -i "$T/in.wav" -af "$PITCH_FILTER" -c:a pcm_s16le "$T/pitch.wav"            || fail "3 pitch: wav -> wav with pitch filter"
dur_ms="$("$PY" -c 'import sys, wave; w = wave.open(sys.argv[1]); print(int(1000 * w.getnframes() / w.getframerate()))' "$T/pitch.wav")" \
  || fail "3 pitch: could not read pitch.wav"
within "$dur_ms" $((SECONDS_LEN * 1000)) 2 || fail "3 pitch: duration ${dur_ms}ms not within 2% of ${SECONDS_LEN}000ms"
ok "3 pitch: duration ${dur_ms}ms"

# 4. separator.decode_with_ffmpeg: decode to f32le stereo 44.1 kHz on stdout
for f in enc.m4a enc.opus enc.mp3 enc.flac enc.ogg enc.webm; do
  n="$("$FF" -hide_banner -loglevel error -nostdin -i "$T/$f" -vn -f f32le -ac 2 -ar 44100 - | wc -c | tr -d ' ')"
  within "$n" "$PCM_EXPECTED" 3 || fail "4 decode: $f gave $n bytes, expected $PCM_EXPECTED +-3%"
done
ok "4 decode: m4a opus mp3 flac ogg webm -> f32le"

# 5. yt-dlp postprocessor shapes
ff -i "$T/enc.opus" -vn -acodec libmp3lame -b:a 320k "$T/yt.mp3"            || fail "5 yt-dlp: opus -> mp3 (FFmpegExtractAudio)"
ff -i "$T/enc.webm" -vn -acodec pcm_s16le "$T/yt.wav"                        || fail "5 yt-dlp: webm -> wav (FFmpegExtractAudio)"
ff -i "$T/enc.m4a" -vn -c copy -f mp4 "$T/yt_copy.m4a"                       || fail "5 yt-dlp: m4a -> m4a stream copy (FFmpegFixupM4a)"
ff -i "$T/enc.m4a" -c copy -f mpegts "$T/yt.ts"                              || fail "5 yt-dlp: m4a -> ts stream copy"
ff -i "$T/yt.ts" -c copy -f mp4 -bsf:a aac_adtstoasc "$T/yt_fix.m4a"         || fail "5 yt-dlp: ts -> m4a aac_adtstoasc (FFmpegFixupM3u8)"
ok "5 yt-dlp: extract-audio, fixup-m4a, fixup-m3u8"

# 6. every produced file decodes cleanly
for f in "$T"/*.mp3 "$T"/*.m4a "$T"/*.opus "$T"/*.ogg "$T"/*.webm "$T"/*.flac "$T"/*.wav "$T"/*.ts; do
  ff -i "$f" -f null - || fail "6 decode-all: $(basename "$f") failed to decode"
done
ok "6 decode-all: every output decodes"

# 7. size guard: a video codec slipping in shows up as a big jump
size="$(nbytes "$FF")"
[ "$size" -le "$MAX_BYTES" ] || fail "7 size: $size bytes > $MAX_BYTES (video codecs pulled in?)"
ok "7 size: $size bytes"
echo "smoke: PASS"
