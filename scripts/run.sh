#!/usr/bin/env bash
# Supervise the API (and optionally the Vite dev server) so a process killed by a
# sandbox restart, an OOM or a crash-loop is brought back without manual action.
#
#   scripts/run.sh              # uvicorn only (serves frontend/dist when built)
#   scripts/run.sh --with-vite  # also run Vite on :5173 for HMR development
#
# Ctrl-C stops both. Non-zero exits are retried with backoff.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-python3}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
WITH_VITE=0
[ "${1:-}" = "--with-vite" ] && WITH_VITE=1

UV_PID=""
VITE_PID=""
STOP_REQUESTED=0
shutdown() {
  STOP_REQUESTED=1
  echo "[run.sh] stopping (uvicorn=${UV_PID} vite=${VITE_PID})"
  [ -n "$UV_PID" ] && kill "$UV_PID" 2>/dev/null
  [ -n "$VITE_PID" ] && kill "$VITE_PID" 2>/dev/null
  exit 0
}
trap shutdown INT TERM

start_uv() {
  ( cd "$ROOT/backend" && exec "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT" ) &
  UV_PID=$!
}

start_uv
if [ "$WITH_VITE" = "1" ]; then
  ( cd "$ROOT/frontend" && npm run dev -- --host 0.0.0.0 ) &
  VITE_PID=$!
fi
echo "[run.sh] uvicorn pid=$UV_PID on http://$HOST:$PORT (UI served from frontend/dist when built)"

fails=0
while :; do
  while kill -0 "$UV_PID" 2>/dev/null; do sleep 2; done
  wait "$UV_PID" 2>/dev/null
  code=$?
  # Only an exit we asked for (Ctrl-C / kill of run.sh, which sets STOP_REQUESTED)
  # stops the loop: a bare `pkill uvicorn` must NOT look like an intentional stop,
  # otherwise the supervisor exits with the API dead.
  if [ "$STOP_REQUESTED" = "1" ]; then
    echo "[run.sh] stop requested - done"; break
  fi
  case "$code" in
    0) echo "[run.sh] uvicorn exited cleanly (0) - done"; break ;;
  esac
  fails=$((fails + 1))
  delay=$(( fails < 4 ? fails * 3 : 10 ))
  echo "[run.sh] uvicorn exited code=$code - restarting in ${delay}s (attempt $fails)"
  [ "$fails" -ge 12 ] && { echo "[run.sh] too many consecutive failures, giving up"; break; }
  sleep "$delay"
  start_uv
done

[ -n "$VITE_PID" ] && kill "$VITE_PID" 2>/dev/null
