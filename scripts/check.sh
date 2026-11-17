#!/usr/bin/env bash
# Zero-dependency local checks.
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m compileall -q agent
python3 -m unittest discover -s tests -p 'test_*.py'
