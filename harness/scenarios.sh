#!/usr/bin/env bash
# Run one capability scenario against the base image.
#
# Usage:
#   OPENCODE_API_KEY=... OPENCODE_STATE_DIR=... \
#     ./harness/scenarios.sh <name> <modules> <sandbox> <port> <prompt>
#
# Example:
#   ./harness/scenarios.sh browser_bwrap browser bwrap 4300 \
#     'Open https://example.com with browser.page(), then return the title.'
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/me-when-agents/packages/opencode/dist/opencode-linux-x64/bin/opencode"

NAME=${1:?scenario name}
MODULES=${2:?modules}
SANDBOX=${3:-bwrap}
PORT=${4:?port}
PROMPT=${5:?prompt}

: "${OPENCODE_API_KEY:?set OPENCODE_API_KEY to a LiteLLM key}"
LITELLM_BASE_URL="${LITELLM_BASE_URL:-https://dashboard.agent.tcl-it.tech/v1}"
export OPENCODE_API_KEY LITELLM_BASE_URL

STATE_DIR="${OPENCODE_STATE_DIR:-}"
if [ -n "$STATE_DIR" ]; then
  rm -rf "$STATE_DIR"
  mkdir -p "$STATE_DIR"
fi

RUN="$ROOT/harness/runs/scenarios/${NAME}-$(date +%Y%m%dT%H%M%S)"
mkdir -p "$RUN/workspace"
"$ROOT/harness/provenance.sh" >"$RUN/provenance.json"
echo "=== scenario $NAME | modules=$MODULES sandbox=$SANDBOX port=$PORT ==="
echo "run: $RUN"

ENVS=(
  "PYTHON_MODULES=$MODULES"
  "OPENCODE_PYTHON_SANDBOX=$SANDBOX"
  "OPENCODE_PYTHON_CODE_MODE=true"
)
env "${ENVS[@]}" PORT="$PORT" KEEP_WORKSPACE=1 "$ROOT/harness/serve.sh" >"$RUN/serve.log" 2>&1 &
SERVE=$!

READY=0
for _ in $(seq 1 120); do
  if curl -sf -m 2 "http://127.0.0.1:$PORT/global/health" >/dev/null; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" != "1" ]; then
  echo "scenario $NAME: server did not become ready" >&2
  tail -30 "$RUN/serve.log" >&2 || true
  kill "$SERVE" 2>/dev/null || true
  wait "$SERVE" 2>/dev/null || true
  exit 1
fi

set +e
"$BIN" run --attach "http://127.0.0.1:$PORT" --model litellm/prometheus \
  --agent python-experiment --dir /home/ubuntu/workspace --auto --format json "$PROMPT" \
  >"$RUN/transcript.jsonl" 2>"$RUN/run.log"
RC=$?
set -e

SESSION=$(python3 - "$RUN/transcript.jsonl" <<'PY'
import json
import sys
for line in open(sys.argv[1]):
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if event.get("sessionID"):
        print(event["sessionID"])
        break
PY
)

CID=$(docker ps -q --filter "publish=$PORT" | head -1)
if [ -n "${SESSION:-}" ] && [ -n "${CID:-}" ]; then
  docker exec -u ubuntu "$CID" /opt/opencode export "$SESSION" >"$RUN/session.json" || true
fi

WORK=$(grep -m1 "workspace kept:" "$RUN/serve.log" | sed 's/workspace kept: //' || true)
if [ -n "${WORK:-}" ] && [ -d "$WORK" ]; then
  cp -a "$WORK/." "$RUN/workspace/"
  rm -rf "$RUN/workspace/.git"
fi

if [ -n "$STATE_DIR" ]; then
  mkdir -p "$RUN/state"
  for file in opencode.db opencode.db-shm opencode.db-wal; do
    [ -f "$STATE_DIR/$file" ] && cp "$STATE_DIR/$file" "$RUN/state/"
  done
fi

if [ -n "${CID:-}" ]; then
  docker stop "$CID" >/dev/null 2>&1 || true
fi
kill "$SERVE" 2>/dev/null || true
wait "$SERVE" 2>/dev/null || true

echo "scenario $NAME: exit $RC session ${SESSION:-none}"
python3 "$ROOT/harness/analyze_run.py" "$RUN" | tail -35
exit "$RC"
