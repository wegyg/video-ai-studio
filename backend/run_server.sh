#!/usr/bin/env bash
# Launch the FastAPI backend (detached). Usage: ./run_server.sh
set -e
cd "$(dirname "$0")"
H="127.0.0.1"
P="8000"
exec .venv/bin/python -m uvicorn app.main:app --host "$H" --port "$P"
