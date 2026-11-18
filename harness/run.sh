#!/usr/bin/env bash
# Run the sandbox harness inside the same base image manus-dei uses.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${MANUS_BASE_IMAGE:-manus-dei/base:latest}"
TMPROOT="${TMPDIR:-/tmp/opencode}"
mkdir -p "$TMPROOT"
WORK="$(mktemp -d "$TMPROOT/enuma-harness.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

cp -a "$ROOT/harness/fixture/." "$WORK/"

echo "harness image: $IMAGE"
echo "workspace:     $WORK"

# bwrap needs unprivileged user namespaces. Docker's default seccomp profile
# blocks them; a real session needs this flag or a custom profile before the
# Python tool can use bwrap.
docker run --rm \
  --security-opt seccomp=unconfined \
  -v "$ROOT:/opt/enuma:ro" \
  -v "$WORK:/home/ubuntu/workspace:rw" \
  --entrypoint /bin/bash \
  "$IMAGE" /opt/enuma/harness/container.sh
