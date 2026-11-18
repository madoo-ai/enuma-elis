#!/usr/bin/env bash
# Serve the built opencode binary inside manus-dei/base and publish the port.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${MANUS_BASE_IMAGE:-manus-dei/base:latest}"
BIN="$ROOT/me-when-agents/packages/opencode/dist/opencode-linux-x64/bin/opencode"
STAMP="$ROOT/me-when-agents/packages/opencode/dist/.built-in-base"
PORT="${PORT:-4096}"
TMPROOT="${TMPDIR:-/tmp/opencode}"
mkdir -p "$TMPROOT"
WORK="$(mktemp -d "$TMPROOT/enuma-serve.XXXXXX")"
if [ "${KEEP_WORKSPACE:-0}" != "1" ]; then
  trap 'rm -rf "$WORK"' EXIT
else
  echo "workspace kept: $WORK"
fi

if [ ! -x "$BIN" ] || [ "$(cat "$STAMP" 2>/dev/null || true)" != "$IMAGE" ]; then
  echo "building opencode inside $IMAGE..."
  "$ROOT/harness/build.sh"
fi

cp -a "$ROOT/harness/fixture/." "$WORK/"

if [ "${GIT_FIXTURE:-1}" = "1" ] && command -v git >/dev/null 2>&1; then
  git -C "$WORK" init -q
  git -C "$WORK" -c user.name=harness -c user.email=harness@example.invalid add -A
  git -C "$WORK" -c user.name=harness -c user.email=harness@example.invalid commit -q -m fixture
fi

ENVS=()
[ -n "${OPENCODE_API_KEY:-}" ] && ENVS+=(-e "OPENCODE_API_KEY=$OPENCODE_API_KEY")
[ -n "${LITELLM_BASE_URL:-}" ] && ENVS+=(-e "LITELLM_BASE_URL=$LITELLM_BASE_URL")
[ -n "${OPENCODE_SERVER_PASSWORD:-}" ] && ENVS+=(-e "OPENCODE_SERVER_PASSWORD=$OPENCODE_SERVER_PASSWORD")
[ -n "${PYTHON_MODULES:-}" ] && ENVS+=(-e "PYTHON_MODULES=$PYTHON_MODULES")
[ -n "${OPENCODE_PYTHON_CODE_MODE:-}" ] && ENVS+=(-e "OPENCODE_PYTHON_CODE_MODE=$OPENCODE_PYTHON_CODE_MODE")
[ -n "${OPENCODE_PYTHON_NETWORK:-}" ] && ENVS+=(-e "OPENCODE_PYTHON_NETWORK=$OPENCODE_PYTHON_NETWORK")
[ -n "${OPENCODE_PYTHON_WORKSPACE:-}" ] && ENVS+=(-e "OPENCODE_PYTHON_WORKSPACE=$OPENCODE_PYTHON_WORKSPACE")
[ -n "${OPENCODE_PYTHON_BLOCK_RAW_EXEC:-}" ] && ENVS+=(-e "OPENCODE_PYTHON_BLOCK_RAW_EXEC=$OPENCODE_PYTHON_BLOCK_RAW_EXEC")
[ -n "${OPENCODE_PYTHON_SANDBOX:-}" ] && ENVS+=(-e "OPENCODE_PYTHON_SANDBOX=$OPENCODE_PYTHON_SANDBOX")

echo "opencode:  $BIN"
echo "image:     $IMAGE"
echo "workspace: $WORK"
echo "url:       http://127.0.0.1:$PORT"

docker run --rm \
  --security-opt seccomp=unconfined \
  -p "$PORT:4096" \
  -v "$ROOT:/opt/enuma:ro" \
  -v "$BIN:/opt/opencode:ro" \
  -v "$WORK:/home/ubuntu/workspace:rw" \
  "${ENVS[@]}" \
  --entrypoint /bin/bash \
  "$IMAGE" /opt/enuma/harness/serve-container.sh
