# Report replay, 2026-11-19

Replays the matrix in `analysis/harness-2026-11-19/report.pdf` with the build
from commit `a3e0dc4` (fork `a805c12e7`). The runner is
`harness/replay-report-2026-11-19.sh`; `matrix.log` is its log.

- Arms: `0`, `B`, `C`, `D` in this batch.
- Arms `A` and `U` ran here first (`A-20261119T175338`, `U-20261119T180018`) but
  their session export was truncated mid-base64, so they have no valid
  `session.json` or `metrics.json`. They were rerun:
  - `arms/A-20261119T180934`
  - `arms/U-20261119T181029`
- Scenarios: all 12 completed in this batch with valid sessions and metrics.

Use the reruns for arm A and U; the first pair is kept only as evidence of the
export bug. The fix writes the export inside the container and copies it out.
