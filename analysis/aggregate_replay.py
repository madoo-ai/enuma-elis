#!/usr/bin/env python3
"""Aggregate the 2026-11-19 replay and compare it with the matching old runs."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aggregate_harness as agg  # noqa: E402

OUT = Path(__file__).resolve().parent / "harness-2026-11-19-replay"

# The replay batch. The two superseded arm attempts are deliberately absent.
NEW = [
    "harness/runs/arms/0-20261119T175247",
    "harness/runs/arms/A-20261119T180934",
    "harness/runs/arms/B-20261119T175726",
    "harness/runs/arms/C-20261119T175817",
    "harness/runs/arms/D-20261119T175942",
    "harness/runs/arms/U-20261119T181029",
    "harness/runs/scenarios/browser_bwrap-20261119T180136",
    "harness/runs/scenarios/browser_none-20261119T180157",
    "harness/runs/scenarios/browser_text_bwrap-20261119T180218",
    "harness/runs/scenarios/jobs_bwrap-20261119T180252",
    "harness/runs/scenarios/jobs_none-20261119T180311",
    "harness/runs/scenarios/detached_bwrap-20261119T180354",
    "harness/runs/scenarios/detached_none-20261119T180421",
    "harness/runs/scenarios/detached_none2-20261119T180452",
    "harness/runs/scenarios/combo_bwrap-20261119T180557",
    "harness/runs/scenarios/combo_none-20261119T180625",
    "harness/runs/scenarios/attachments_bwrap-20261119T180649",
    "harness/runs/scenarios/attachments_none-20261119T180751",
]

OLD = [
    "0-20261119T013043",
    "A-20261119T020147",
    "B-20261119T020443",
    "C-20261119T020531",
    "D-20261119T020616",
    "U-20261119T020727",
    "attachments_bwrap-20261119T022143",
    "attachments_none-20261119T022219",
    "browser_bwrap-20261119T021223",
    "browser_none-20261119T021633",
    "browser_text_bwrap-20261119T025558",
    "combo_bwrap-20261119T025356",
    "combo_none-20261119T025436",
    "detached_bwrap-20261119T021906",
    "detached_none-20261119T021951",
    "detached_none2-20261119T022051",
    "jobs_bwrap-20261119T021803",
    "jobs_none-20261119T021832",
]


def summarize(runs):
    audit = Counter()
    for run in runs:
        metrics = run["metrics"] or {}
        audit.update(metrics.get("audit") or {})
    return {
        "runs": len(runs),
        "python_calls": sum(run["python_call_count"] for run in runs),
        "python_ok": sum(run["python_ok_count"] for run in runs),
        "python_failed": sum(run["python_failed_count"] for run in runs),
        "python_recovered": sum(1 for run in runs if run["python_recovery"]),
        "child_calls": sum(sum(run["child_tools"].values()) for run in runs),
        "child_tools": dict(sum((Counter(run["child_tools"]) for run in runs), Counter())),
        "tool_module_usage": dict(sum((Counter(run["tool_module_usage"]) for run in runs), Counter())),
        "program_tags": dict(sum((Counter(run["program_tags"]) for run in runs), Counter())),
        "error_kinds": dict(sum((Counter(run["error_kinds"]) for run in runs), Counter())),
        "errors": sum((run["metrics"] or {}).get("errors") or 0 for run in runs),
        "duration_seconds": round(sum((run["metrics"] or {}).get("durationSeconds") or 0 for run in runs), 1),
        "raw_open": audit.get("rawOpen", 0),
        "raw_exec": audit.get("rawExec", 0),
        "raw_net": audit.get("rawNet", 0),
        "verification": {
            key: sum(1 for run in runs if run["verification_words"][key])
            for key in ("verified", "read_back", "limitation", "browser_check", "static_check")
        },
    }


def main() -> None:
    runs = [agg.summarize_run(ROOT / path) for path in NEW]
    old_all = json.loads((ROOT / "analysis/harness-2026-11-19/runs.json").read_text())
    old_by_id = {run["id"]: run for run in old_all}
    old = [old_by_id[name] for name in OLD]
    missing = [name for name in OLD if name not in old_by_id]
    if missing:
        raise SystemExit(f"missing old runs: {missing}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs.json").write_text(json.dumps(runs, indent=2) + "\n")
    summary = {"new": summarize(runs), "old": summarize(old), "runs": runs}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    fields = [
        "id", "category", "label", "duration_seconds", "errors", "python_calls", "python_ok",
        "python_failed", "python_recovery", "child_calls", "raw_open", "raw_exec", "raw_net",
        "files_changed", "verified", "browser_check",
    ]
    with (OUT / "runs.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            metrics = run["metrics"] or {}
            audit = metrics.get("audit") or {}
            writer.writerow({
                "id": run["id"], "category": run["category"], "label": run["label"],
                "duration_seconds": metrics.get("durationSeconds"), "errors": metrics.get("errors"),
                "python_calls": run["python_call_count"], "python_ok": run["python_ok_count"],
                "python_failed": run["python_failed_count"], "python_recovery": run["python_recovery"],
                "child_calls": sum(run["child_tools"].values()), "raw_open": audit.get("rawOpen", 0),
                "raw_exec": audit.get("rawExec", 0), "raw_net": audit.get("rawNet", 0),
                "files_changed": len(metrics.get("filesChanged") or []),
                "verified": run["verification_words"]["verified"],
                "browser_check": run["verification_words"]["browser_check"],
            })

    print(json.dumps({"new": summary["new"], "old": summary["old"]}, indent=2))
    print("\nNEW RUNS")
    for run in runs:
        metrics = run["metrics"] or {}
        print(
            f"{run['id']:52s} {metrics.get('durationSeconds'):>6}s "
            f"py={run['python_ok_count']}/{run['python_call_count']} "
            f"child={sum(run['child_tools'].values()):>2} "
            f"err={metrics.get('errors')} raw={metrics.get('audit')} "
            f"files={len(metrics.get('filesChanged') or [])}"
        )


if __name__ == "__main__":
    main()
