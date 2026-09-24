#!/usr/bin/env bash
# Builds an audio-only, statically linked ffmpeg from the official source release.
# Runs on MSYS2 MINGW64 (CI, produces ffmpeg.exe) and on macOS (local validation).
#
# Usage: bash tools/ffmpeg/build.sh
# Env:   FFMPEG_VERSION, FFMPEG_SHA256 (override together), OUT_DIR (default tools/ffmpeg/out)
set -eu

FFMPEG_VERSION="${FFMPEG_VERSION:-9.0.2}"
# sha256 of ffmpeg-9.0.2.tar.xz (release tarball verified against its .asc signature
# from the FFmpeg release signing key FCF986EA15E6E293A5644F10B4322F04D67658D8).
FFMPEG_SHA256="${FFMPEG_SHA256:-8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e}"

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${OUT_DIR:-$HERE/out}"
SRC_ROOT="$HERE/src"
TARBALL="$SRC_ROOT/ffmpeg-$FFMPEG_VERSION.tar.xz"
SRC="$SRC_ROOT/ffmpeg-$FFMPEG_VERSION"

fail() { echo "build.sh: $*" >&2; exit 1; }

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

ncpu() { nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2; }

# --- source ------------------------------------------------------------------
mkdir -p "$SRC_ROOT" "$OUT_DIR"
if [ ! -f "$TARBALL" ] || [ "$(sha256_of "$TARBALL")" != "$FFMPEG_SHA256" ]; then
  curl -fL --retry 3 -o "$TARBALL" "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" \
    || fail "download failed for ffmpeg-$FFMPEG_VERSION.tar.xz"
fi
got="$(sha256_of "$TARBALL")"
[ "$got" = "$FFMPEG_SHA256" ] || fail "sha256 mismatch: got $got, expected $FFMPEG_SHA256"
rm -rf "$SRC"
tar -xJf "$TARBALL" -C "$SRC_ROOT"
cd "$SRC"

# --- component lists, generated from the source -------------------------------
# Every native audio decoder: allcodecs.c from "/* audio codecs */" up to "/* subtitles */"
# (covers the PCM / DPCM / ADPCM blocks; external-library decoders come later in the file).
join_commas() { tr '\n' ',' | sed 's/,$//'; }

AUDIO_DECODERS="$(awk '/^\/\* audio codecs \*\//{p=1} /^\/\* subtitles \*\//{p=0} p' libavcodec/allcodecs.c \
  | grep -o 'ff_[a-z0-9_]*_decoder' | sed 's/^ff_//; s/_decoder$//' | sort -u | join_commas)"
# Every native demuxer / muxer: allformats.c up to "/* external libraries */".
NATIVE_FORMATS="$(awk '/^\/\* external libraries \*\//{exit} {print}' libavformat/allformats.c)"
DEMUXERS="$(printf '%s\n' "$NATIVE_FORMATS" | grep -o 'ff_[a-z0-9_]*_demuxer' \
  | sed 's/^ff_//; s/_demuxer$//' | sort -u | join_commas)"
MUXERS="$(printf '%s\n' "$NATIVE_FORMATS" | grep -o 'ff_[a-z0-9_]*_muxer' \
  | sed 's/^ff_//; s/_muxer$//' | sort -u | join_commas)"
[ -n "$AUDIO_DECODERS" ] && [ -n "$DEMUXERS" ] && [ -n "$MUXERS" ] \
  || fail "component list extraction came back empty (source layout changed?)"

ENCODERS='libmp3lame,aac,libopus,flac,alac,pcm_*'
FILTERS='aresample,aformat,anull,abuffer,abuffersink,asetrate,atempo,volume,apad,atrim,asetpts,aselect,anullsrc,amix,amerge,pan,channelmap,channelsplit,join,concat,afade,adelay,silencedetect'
# No 'hls' protocol: it no longer exists upstream; HLS input goes through the hls demuxer.
PROTOCOLS='file,pipe,data,concat,tcp,http,https,tls,crypto'

# --- platform -----------------------------------------------------------------
case "$(uname -s)" in
  MINGW*|MSYS*)
    EXE=ffmpeg.exe
    PLATFORM_FLAGS="--enable-w32threads --enable-schannel --extra-ldflags=-static"
    ;;
  Darwin)
    EXE=ffmpeg
    BREW="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"
    PLATFORM_FLAGS="--enable-pthreads --enable-securetransport --extra-cflags=-I$BREW/include --extra-ldflags=-L$BREW/lib"
    ;;
  *)
    EXE=ffmpeg
    PLATFORM_FLAGS="--enable-pthreads"
    ;;
esac

# --- configure / make -----------------------------------------------------------
# --disable-autodetect also turns off threads and zlib, so both are enabled explicitly.
# PLATFORM_FLAGS is intentionally unquoted (word splitting into separate options).
# shellcheck disable=SC2086
./configure --prefix="$SRC/_install" \
  --disable-everything --disable-doc --disable-ffplay --disable-ffprobe --disable-debug \
  --disable-autodetect --disable-avdevice --disable-swscale \
  --enable-static --disable-shared --pkg-config-flags=--static \
  --enable-gpl --enable-zlib --enable-libmp3lame --enable-libopus \
  $PLATFORM_FLAGS \
  --enable-protocol="$PROTOCOLS" \
  --enable-demuxer="$DEMUXERS" \
  --enable-muxer="$MUXERS" \
  --enable-decoder="$AUDIO_DECODERS" \
  --enable-encoder="$ENCODERS" \
  --enable-parser='*' \
  --enable-bsf='*' \
  --enable-filter="$FILTERS" \
  > "$SRC_ROOT/configure.log" 2>&1 \
  || { tail -n 30 "$SRC_ROOT/configure.log" >&2; fail "configure failed (full log: $SRC_ROOT/configure.log)"; }
grep -i 'warning' "$SRC_ROOT/configure.log" || true

make -j"$(ncpu)" ffmpeg > "$SRC_ROOT/make.log" 2>&1 \
  || { tail -n 30 "$SRC_ROOT/make.log" >&2; fail "make failed (full log: $SRC_ROOT/make.log)"; }

# ffmpeg_g is the unstripped binary; ffmpeg is already stripped by the Makefile, strip again to be sure.
cp "$EXE" "$OUT_DIR/$EXE"
strip "$OUT_DIR/$EXE" 2>/dev/null || true
echo "built $OUT_DIR/$EXE ($(wc -c < "$OUT_DIR/$EXE" | tr -d ' ') bytes, ffmpeg $FFMPEG_VERSION)"
