#!/usr/bin/env bash
# Launch the FastAPI backend (detached). Usage: ./run_server.sh
set -e
cd "$(dirname "$0")"
bash ../scripts/setup_python.sh
bash ../scripts/setup_ffmpeg.sh   # ffmpeg on PATH (no-op if already fine)
bash ../scripts/setup_fonts.sh   # CJK glyphs for Korean/Japanese/Chinese captions
H="127.0.0.1"
P="8000"
exec .venv/bin/python -m uvicorn app.main:app --host "$H" --port "$P"
