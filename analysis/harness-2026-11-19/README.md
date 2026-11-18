# Harness analysis, 2026-11-19

This directory contains the quantitative and semantic analysis of the Python
code-mode harness corpus.

## Read

- `report.pdf` — full analysis, 18 pages.
- `report.tex` — LaTeX source.

## Data

- `runs.json` — per-run and per-Python-program features.
- `runs.csv` — compact quantitative table.
- `summary.json` — aggregate counters.

## Regenerate

```bash
python3 analysis/aggregate_harness.py
pdflatex -interaction=nonstopmode -halt-on-error analysis/harness-2026-11-19/report.tex
pdflatex -interaction=nonstopmode -halt-on-error analysis/harness-2026-11-19/report.tex
```

The aggregation reads every run with a `metrics.json` under `harness/runs/`.
