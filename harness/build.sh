#!/usr/bin/env bash
# Build the fork binary inside manus-dei/base so it matches the session libc.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${MANUS_BASE_IMAGE:-manus-dei/base:latest}"
ORIG="${MANUS_FORK_ORIG:-/home/x1nx3r/prototypes/manus-dei/ref/me-when-agents}"
SRC="$ROOT/me-when-agents"

if [ ! -d "$ORIG/node_modules" ]; then
  echo "missing $ORIG/node_modules; set MANUS_FORK_ORIG" >&2
  exit 1
fi

# The copy's node_modules symlinks point at the original checkout. Mount the
# original at its real path so they resolve, and overlay the one changed core
# file so the build sees the new agent config fields.
docker run --rm \
  --security-opt seccomp=unconfined \
  -v "$SRC:/src:rw" \
  -v "$ORIG:$ORIG:ro" \
  -v "$SRC/packages/core/src/v1/config/agent.ts:$ORIG/packages/core/src/v1/config/agent.ts:ro" \
  -v "$ROOT/harness/build-container.sh:/opt/build.sh:ro" \
  -e "MANUS_BASE_IMAGE=$IMAGE" \
  --entrypoint /bin/bash \
  "$IMAGE" /opt/build.sh
