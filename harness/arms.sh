#!/usr/bin/env bash
# Run the Phase 2 experiment arms against the base image.
#
# Requires OPENCODE_API_KEY (a LiteLLM key) and LITELLM_BASE_URL.
#   ./harness/arms.sh B
#   ./harness/arms.sh 0 A B C D
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/me-when-agents/packages/opencode/dist/opencode-linux-x64/bin/opencode"
ARMS=("$@")
if [ ${#ARMS[@]} -eq 0 ]; then
  ARMS=(0 A B C D)
fi

: "${OPENCODE_API_KEY:?set OPENCODE_API_KEY to a LiteLLM key}"
LITELLM_BASE_URL="${LITELLM_BASE_URL:-https://dashboard.agent.tcl-it.tech/v1}"
export OPENCODE_API_KEY LITELLM_BASE_URL

PROMPT="${PROMPT:-Build a small to-do app in the current workspace. Keep it to one HTML file with add, complete, and delete, persisted in localStorage. Use the available tools and read the file back to verify.}"

if [ ! -x "$BIN" ]; then
  "$ROOT/harness/build.sh"
fi

for index in "${!ARMS[@]}"; do
  ARM="${ARMS[$index]}"
  case "$ARM" in
    0)
      MODE=false
      AGENT=build
      MODULES=""
      WORKSPACE=rw
      NETWORK=true
      BLOCK=0
      ;;
    A)
      MODE=true
      AGENT=python-experiment
      MODULES=fs,mutate,shell,web,state,agents
      WORKSPACE=rw
      NETWORK=true
      BLOCK=0
      ;;
    B)
      MODE=true
      AGENT=python-experiment
      MODULES=fs,mutate,web,state
      WORKSPACE=rw
      NETWORK=true
      BLOCK=1
      ;;
    C)
      MODE=true
      AGENT=python-experiment
      MODULES=fs,mutate,web,state
      WORKSPACE=ro
      NETWORK=true
      BLOCK=1
      ;;
    D)
      MODE=true
      AGENT=python-experiment
      MODULES=fs,mutate,state
      WORKSPACE=ro
      NETWORK=false
      BLOCK=1
      ;;
    *)
      echo "unknown arm: $ARM (use 0, A, B, C, D)" >&2
      exit 1
      ;;
  esac

  PORT=$((4100 + index))
  RUN="$ROOT/harness/runs/arms/${ARM}-$(date +%Y%m%dT%H%M%S)"
  mkdir -p "$RUN/workspace"
  echo "=== arm $ARM | port $PORT | $RUN ==="

  ENVV=(
    "OPENCODE_PYTHON_CODE_MODE=$MODE"
    "OPENCODE_PYTHON_WORKSPACE=$WORKSPACE"
    "OPENCODE_PYTHON_NETWORK=$NETWORK"
    "OPENCODE_PYTHON_BLOCK_RAW_EXEC=$BLOCK"
  )
  [ -n "$MODULES" ] && ENVV+=("PYTHON_MODULES=$MODULES")

  env "${ENVV[@]}" PORT="$PORT" KEEP_WORKSPACE=1 "$ROOT/harness/serve.sh" >"$RUN/serve.log" 2>&1 &
  SERVE=$!

  READY=0
  for _ in $(seq 1 90); do
    if curl -sf -m 2 "http://127.0.0.1:$PORT/global/health" >/dev/null; then
      READY=1
      break
    fi
    sleep 1
  done
  if [ "$READY" != "1" ]; then
    echo "arm $ARM: server did not become ready" >&2
    tail -20 "$RUN/serve.log" >&2 || true
    kill "$SERVE" 2>/dev/null || true
    wait "$SERVE" 2>/dev/null || true
    continue
  fi

  set +e
  "$BIN" run --attach "http://127.0.0.1:$PORT" --model litellm/prometheus \
    --agent "$AGENT" --dir /home/ubuntu/workspace --auto --format json "$PROMPT" \
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

  if [ -n "${CID:-}" ]; then
    docker stop "$CID" >/dev/null 2>&1 || true
  fi
  kill "$SERVE" 2>/dev/null || true
  wait "$SERVE" 2>/dev/null || true

  echo "arm $ARM: exit $RC, session ${SESSION:-none}"
  python3 "$ROOT/harness/analyze_run.py" "$RUN" | tail -25
done
