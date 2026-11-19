#!/usr/bin/env python3
"""Summarize a dumped harness run into metrics.json and a short table."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def from_session(run: Path) -> dict:
    data = json.loads((run / "session.json").read_text())
    tools: Counter[str] = Counter()
    child: Counter[str] = Counter()
    audits: Counter[str] = Counter()
    files: set[str] = set()
    tokens: Counter[str] = Counter()
    times: list[int] = []
    texts: list[str] = []
    steps = 0
    cost = 0.0
    errors = 0

    for message in data.get("messages", []):
        info = message.get("info") or {}
        time = info.get("time") or {}
        for key in ("created", "updated", "completed"):
            if time.get(key):
                times.append(time[key])

        for part in message.get("parts", []):
            kind = part.get("type")
            if kind == "tool":
                tools[part.get("tool")] += 1
                state = part.get("state") or {}
                meta = state.get("metadata") or {}
                for call in meta.get("toolCalls") or []:
                    child[call.get("tool")] += 1
                for key, value in (meta.get("audit") or {}).items():
                    audits[key] += value or 0
                for file in meta.get("filesChanged") or []:
                    files.add(file)
                if meta.get("error") or str(state.get("output", "")).startswith("Python program failed"):
                    errors += 1
            elif kind == "step-finish":
                steps += 1
                usage = part.get("tokens") or {}
                for key in ("input", "output", "reasoning"):
                    tokens[key] += usage.get(key, 0) or 0
                tokens["cacheRead"] += (usage.get("cache") or {}).get("read", 0) or 0
                cost += part.get("cost", 0) or 0
            elif kind == "text" and info.get("role") == "assistant" and not part.get("synthetic"):
                texts.append(part.get("text") or "")

    return {
        "source": "session.json",
        "steps": steps,
        "tools": dict(tools),
        "childTools": dict(child),
        "tokens": dict(tokens),
        "cost": cost,
        "errors": errors,
        "audit": dict(audits),
        "filesChanged": sorted(files),
        "durationSeconds": round((max(times) - min(times)) / 1000, 1) if times else None,
        "finalText": texts[-1] if texts else "",
    }


def from_transcript(run: Path) -> dict:
    tools: Counter[str] = Counter()
    child: Counter[str] = Counter()
    audits: Counter[str] = Counter()
    files: set[str] = set()
    tokens: Counter[str] = Counter()
    times: list[int] = []
    steps = 0
    cost = 0.0
    errors = 0

    for line in (run / "transcript.jsonl").read_text().splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("timestamp"):
            times.append(event["timestamp"])
        part = event.get("part") or {}
        if event.get("type") == "step_start":
            steps += 1
        elif event.get("type") == "step_finish":
            usage = part.get("tokens") or {}
            for key in ("input", "output", "reasoning"):
                tokens[key] += usage.get(key, 0) or 0
            tokens["cacheRead"] += (usage.get("cache") or {}).get("read", 0) or 0
            cost += part.get("cost", 0) or 0
        elif event.get("type") == "tool_use":
            tools[part.get("tool")] += 1
            state = part.get("state") or {}
            meta = state.get("metadata") or {}
            for call in meta.get("toolCalls") or []:
                child[call.get("tool")] += 1
            for key, value in (meta.get("audit") or {}).items():
                audits[key] += value or 0
            for file in meta.get("filesChanged") or []:
                files.add(file)
            if meta.get("error") or str(state.get("output", "")).startswith("Python program failed"):
                errors += 1

    return {
        "source": "transcript.jsonl",
        "steps": steps,
        "tools": dict(tools),
        "childTools": dict(child),
        "tokens": dict(tokens),
        "cost": cost,
        "errors": errors,
        "audit": dict(audits),
        "filesChanged": sorted(files),
        "durationSeconds": round((max(times) - min(times)) / 1000, 1) if times else None,
        "finalText": "",
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: analyze_run.py <run-dir>", file=sys.stderr)
        return 2
    run = Path(sys.argv[1])
    if (run / "session.json").exists():
        metrics = from_session(run)
    elif (run / "transcript.jsonl").exists():
        metrics = from_transcript(run)
    else:
        print(f"no session.json or transcript.jsonl in {run}", file=sys.stderr)
        return 1

    workspace = run / "workspace"
    if workspace.is_dir():
        files = []
        for path in sorted(workspace.rglob("*")):
            if path.is_file() and ".git" not in path.parts:
                files.append({"path": str(path.relative_to(workspace)), "bytes": path.stat().st_size})
        metrics["workspace"] = files

    (run / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    provenance_path = run / "provenance.json"
    if provenance_path.exists():
        try:
            provenance = json.loads(provenance_path.read_text())
        except (OSError, json.JSONDecodeError):
            provenance = None
        if provenance:
            metrics["provenance"] = provenance
            (run / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps({key: metrics[key] for key in metrics if key != "finalText"}, indent=2))
    if metrics.get("finalText"):
        print("\nFINAL:\n" + metrics["finalText"][:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
