# Harness replay report, 2026-11-19

- `report.pdf` — the report (9 pages).
- `report.tex` — its source.
- `summary.json` — aggregate old and replay totals.
- `runs.json` — per-run analysis, with the Python program features.
- `runs.csv` — one row per replay run.

The replay repeats the six arms and twelve capability scenarios from
`analysis/harness-2026-11-19/report.pdf` on root `a3e0dc4` / fork `a805c12e7`.
Prompts, module lists, and sandboxes are unchanged. The scratch browser was
disabled for every run.

## Headline

| Measure | First corpus | Replay |
| --- | --- | --- |
| Python programs | 100 | 50 |
| Succeeded | 83 (83.0%) | 47 (94.0%) |
| Failed | 17 | 3 |
| Scenario time | 407.0 s | 161.7 s |
| Browser scenarios | 270.4 s, 7 failures | 21.9 s, 0 failures |
| Raw exec / net | 0 / 0 | 0 / 0 |
| Raw open | 0 | 6 (all `Screenshot.save`) |

The three replay failures are API-shape mismatches: `is_("disabled")`,
`find_all(...)[0].check()` on a `Node`, and `from agent import agent`. The
report recommends one-line fixes for each.

## Runs

The compared runs are listed in Appendix A of the report. The batch log is
`harness/runs/replay-20261119T175247/matrix.log`. Two superseded arm attempts
(`A-20261119T175338`, `U-20261119T180018`) are excluded because their exports
were truncated; their reruns are the compared runs.

## Rebuild

```bash
python3 analysis/aggregate_replay.py
cd analysis/harness-2026-11-19-replay
pdflatex report.tex && pdflatex report.tex
```
