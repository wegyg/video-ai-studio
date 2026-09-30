#!/usr/bin/env bash
# Make sure a static FFmpeg with the filters this project needs is on PATH.
#
# Safe to run many times: if a usable ffmpeg/ffprobe is already available it
# exits immediately. Otherwise it reuses a static build found on the machine, or
# downloads one (johnvansickle, GPL static, no system packages needed).
#
# Env overrides:
#   FFMPEG_DIR      where to keep the downloaded build (default ~/.local/share/video-ai-studio/ffmpeg)
#   FFMPEG_BIN_DIR  where to link ffmpeg/ffprobe (default /usr/local/bin)
set -euo pipefail

# Filters the render pipeline depends on. drawtext is NOT required: captions and
# graphics are drawn with PIL into transparent PNGs and composited with overlay.
NEED_FILTERS="xfade acrossfade adelay apad zoompan fade afade overlay scale crop amix"
INSTALL_DIR="${FFMPEG_DIR:-$HOME/.local/share/video-ai-studio/ffmpeg}"
BIN_DIR="${FFMPEG_BIN_DIR:-/usr/local/bin}"
URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"

log() { printf '[ffmpeg] %s\n' "$*"; }

has_filters() {
  local bin="$1" list f
  [ -x "$bin" ] || return 1
  list="$("$bin" -hide_banner -filters 2>/dev/null)" || return 1
  for f in $NEED_FILTERS; do
    printf '%s\n' "$list" | grep -qE "^ *[A-Z.]+ +$f " || return 1
  done
}

usable_pair() { # $1=ffmpeg $2=ffprobe
  [ -x "${1:-}" ] && [ -x "${2:-}" ] && has_filters "$1" && "$2" -hide_banner -version >/dev/null 2>&1
}

link_pair() { # $1=ffmpeg $2=ffprobe
  if [ -w "$BIN_DIR" ] 2>/dev/null; then
    ln -sf "$1" "$BIN_DIR/ffmpeg"
    ln -sf "$2" "$BIN_DIR/ffprobe"
    log "linked -> $BIN_DIR/{ffmpeg,ffprobe}"
  else
    log "cannot write $BIN_DIR. Add this to your shell instead:"
    log "  export PATH=\"$(dirname "$1"):\$PATH\""
  fi
}

# 1) Already good on PATH?
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1 \
   && has_filters "$(command -v ffmpeg)"; then
  log "already available: $(ffmpeg -hide_banner -version | head -1)"
  exit 0
fi

# 2) A build this script installed earlier?
if usable_pair "$INSTALL_DIR/ffmpeg" "$INSTALL_DIR/ffprobe"; then
  log "reusing $INSTALL_DIR"
  link_pair "$INSTALL_DIR/ffmpeg" "$INSTALL_DIR/ffprobe"
  exit 0
fi

# 3) A static build that happens to be on this machine (e.g. npm ffmpeg-static).
for cand in \
  /usr/local/bin/ffmpeg /opt/ffmpeg/ffmpeg \
  "$HOME"/.local/bin/ffmpeg \
  /projects/sandbox/*/node_modules/ffmpeg-static/ffmpeg
do
  [ -x "$cand" ] || continue
  probe="$(dirname "$cand")/ffprobe"
  [ -x "$probe" ] || probe="$(ls /projects/sandbox/*/node_modules/ffprobe-static/bin/linux/x64/ffprobe 2>/dev/null | head -1 || true)"
  if usable_pair "$cand" "${probe:-}"; then
    log "found existing static build: $cand"
    mkdir -p "$INSTALL_DIR"
    cp -f "$cand" "$INSTALL_DIR/ffmpeg"
    cp -f "$probe" "$INSTALL_DIR/ffprobe"
    link_pair "$INSTALL_DIR/ffmpeg" "$INSTALL_DIR/ffprobe"
    exit 0
  fi
done

# 4) Download a static build.
log "downloading static build (~80MB)…"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fsSL --retry 3 -o "$tmp/ff.tar.xz" "$URL"
tar -xJf "$tmp/ff.tar.xz" -C "$tmp"
src="$(find "$tmp" -maxdepth 2 -type f -name ffmpeg -perm -u+x | head -1)"
[ -n "$src" ] || { log "download did not contain an ffmpeg binary"; exit 1; }
mkdir -p "$INSTALL_DIR"
install -m 0755 "$src" "$INSTALL_DIR/ffmpeg"
install -m 0755 "$(dirname "$src")/ffprobe" "$INSTALL_DIR/ffprobe"

usable_pair "$INSTALL_DIR/ffmpeg" "$INSTALL_DIR/ffprobe" || {
  log "downloaded build is missing required filters: $NEED_FILTERS"
  exit 1
}
link_pair "$INSTALL_DIR/ffmpeg" "$INSTALL_DIR/ffprobe"
log "installed: $("$INSTALL_DIR/ffmpeg" -hide_banner -version | head -1)"
