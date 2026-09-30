#!/usr/bin/env bash
# Start the server, run the HTTP E2E tests, then shut the server down.
set -e
cd "$(dirname "$0")"
bash ../scripts/setup_python.sh
bash ../scripts/setup_ffmpeg.sh
bash ../scripts/setup_fonts.sh   # CJK glyphs for Korean/Japanese/Chinese captions
bash run_server.sh > /projects/sandbox/backend.log 2>&1 &
SRV=$!
# wait for readiness
for i in $(seq 1 20); do
  if .venv/bin/python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/api/health',timeout=2).status_code==200 else 1)" 2>/dev/null; then
    break
  fi
  sleep 1
done
set +e
.venv/bin/python test_http.py
RC=$?
kill "$SRV" 2>/dev/null
wait "$SRV" 2>/dev/null
exit $RC
