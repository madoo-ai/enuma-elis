#!/usr/bin/env bash
# Runs inside manus-dei/base as the `ubuntu` user.
set -euo pipefail

curl -fsSL https://bun.sh/install | bash >/tmp/bun-install.log 2>&1
export PATH="$HOME/.bun/bin:$PATH"

cd /src
bun run --cwd packages/opencode build --single --skip-embed-web-ui --skip-install

BIN=/src/packages/opencode/dist/opencode-linux-x64/bin/opencode
ls -l "$BIN"
"$BIN" --version
echo "${MANUS_BASE_IMAGE:-manus-dei/base:latest}" > /src/packages/opencode/dist/.built-in-base
