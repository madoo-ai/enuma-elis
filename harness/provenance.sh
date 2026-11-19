#!/usr/bin/env bash
# Print the provenance of a harness run as JSON. Intended to be captured into
# a run directory by the harness scripts.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FORK="$ROOT/me-when-agents"
BIN="${OPENCODE_BINARY:-$FORK/packages/opencode/dist/opencode-linux-x64/bin/opencode}"
IMAGE="${MANUS_BASE_IMAGE:-manus-dei/base:latest}"

commit=$(git -C "$FORK" rev-parse HEAD)
version=$("$BIN" --version)
sha256=$(sha256sum "$BIN" | cut -d' ' -f1)

python3 - "$commit" "$version" "$sha256" "$IMAGE" "$BIN" <<'PY'
import json
import os
import sys

commit, version, sha256, image, binary = sys.argv[1:]
print(json.dumps({
    "fork_commit": commit,
    "binary_version": version,
    "binary_sha256": sha256,
    "base_image": image,
    "binary_path": os.path.abspath(binary),
}, sort_keys=True))
PY
