#!/usr/bin/env bash
# Ensure backend/.venv exists with the backend dependencies installed.
#
# Safe to run many times: exits immediately when the venv already works. Also
# repairs a venv whose interpreter disappeared (e.g. a rebuilt dev machine).
set -euo pipefail

cd "$(dirname "$0")/.."
VENV="backend/.venv"
PY="$VENV/bin/python"
DEPS=(fastapi "uvicorn[standard]" pydantic pydantic-settings python-multipart httpx pillow gTTS)

log() { printf '[python] %s\n' "$*"; }

works() { [ -x "$PY" ] && "$PY" -c 'import fastapi, pydantic, PIL, httpx' >/dev/null 2>&1; }

if works; then
  log "venv ready ($("$PY" --version))"
  exit 0
fi

if [ -e "$VENV" ] && ! [ -x "$PY" ]; then
  log "venv interpreter is gone — recreating"
  rm -rf "$VENV"
fi

# Build the venv with whatever 3.11+ tool this machine has.
if command -v uv >/dev/null 2>&1; then
  log "creating venv with uv"
  uv venv --python 3.11 "$VENV" >/dev/null
  log "installing dependencies"
  uv pip install --quiet --python "$PY" "${DEPS[@]}"
else
  PYBIN=""
  for c in python3.11 python3.12 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'; then
      PYBIN="$c"; break
    fi
  done
  [ -n "$PYBIN" ] || { log "need Python 3.11+ (or uv) on PATH"; exit 1; }
  log "creating venv with $PYBIN"
  "$PYBIN" -m venv "$VENV"
  log "installing dependencies"
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet "${DEPS[@]}"
fi

works || { log "dependency install failed"; exit 1; }
log "venv ready ($("$PY" --version))"
