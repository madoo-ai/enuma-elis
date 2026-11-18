#!/usr/bin/env python3
"""Aggregate harness runs into one analyzable JSON document.

Reads every run under ``harness/runs`` that has a ``metrics.json``, parses the
transcript for Python programs, and emits semantic features alongside the raw
metrics. The output is intentionally plain JSON so it can be inspected without
pandas or a notebook.
"""

from __future__ import annotations

import ast
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "harness-2026-11-19"

ARM_CONFIG = {
    "0": {"agent": "build", "python": False, "modules": [], "sandbox": "bwrap", "workspace": "rw", "network": True, "block_raw_exec": False},
    "A": {"agent": "python-experiment", "python": True, "modules": ["fs", "mutate", "shell", "web", "state", "agents"], "sandbox": "bwrap", "workspace": "rw", "network": True, "block_raw_exec": False},
    "B": {"agent": "python-experiment", "python": True, "modules": ["fs", "mutate", "web", "state"], "sandbox": "bwrap", "workspace": "rw", "network": True, "block_raw_exec": True},
    "C": {"agent": "python-experiment", "python": True, "modules": ["fs", "mutate", "web", "state"], "sandbox": "bwrap", "workspace": "ro", "network": True, "block_raw_exec": True},
    "D": {"agent": "python-experiment", "python": True, "modules": ["fs", "mutate", "state"], "sandbox": "bwrap", "workspace": "ro", "network": False, "block_raw_exec": True},
    "U": {"agent": "python-experiment", "python": True, "modules": ["fs", "mutate", "shell", "web", "state", "agents", "browser"], "sandbox": "none", "workspace": "rw", "network": True, "block_raw_exec": False},
}

SCENARIO_CONFIG = {
    "attachments_bwrap": {"modules": ["fs", "shell", "web"], "sandbox": "bwrap", "capability": ["attachments", "jobs"]},
    "attachments_none": {"modules": ["fs", "shell", "web"], "sandbox": "none", "capability": ["attachments", "jobs"]},
    "browser_bwrap": {"modules": ["browser"], "sandbox": "bwrap", "capability": ["browser"]},
    "browser_none": {"modules": ["browser"], "sandbox": "none", "capability": ["browser"]},
    "browser_text_bwrap": {"modules": ["browser"], "sandbox": "bwrap", "capability": ["browser"]},
    "combo_bwrap": {"modules": ["fs", "agents"], "sandbox": "bwrap", "capability": ["jobs", "detached-task"]},
    "combo_none": {"modules": ["fs", "agents"], "sandbox": "none", "capability": ["jobs", "detached-task"]},
    "detached_bwrap": {"modules": ["fs", "agents"], "sandbox": "bwrap", "capability": ["detached-task"]},
    "detached_none": {"modules": ["fs", "agents"], "sandbox": "none", "capability": ["detached-task"]},
    "detached_none2": {"modules": ["fs", "agents"], "sandbox": "none", "capability": ["detached-task"]},
    "jobs_bwrap": {"modules": ["fs"], "sandbox": "bwrap", "capability": ["jobs"]},
    "jobs_none": {"modules": ["fs"], "sandbox": "none", "capability": ["jobs"]},
}

TOOL_MODULES = {
    "fs.read": "fs", "fs.glob": "fs", "fs.grep": "fs",
    "mutate.edit": "mutate", "mutate.write": "mutate", "mutate.patch": "mutate",
    "shell.run": "shell",
    "web.fetch": "web", "web.search": "web",
    "state.skills.load": "state", "state.todos.write": "state",
    "agents.tasks.run": "agents", "agents.tasks.start": "agents",
    "browser.call": "browser",
}

KNOWN_CALLS = {
    "agent.jobs.start": "agent.jobs.start",
    "jobs.start": "agent.jobs.start",
    "agent.jobs.gather": "agent.jobs.gather",
    "agent.jobs.wait_all": "agent.jobs.wait_all",
    "agents.tasks.start": "agents.tasks.start",
    "agents.tasks.run": "agents.tasks.run",
    "browser.page": "browser.page",
    "fs.read": "fs.read", "fs.glob": "fs.glob", "fs.grep": "fs.grep",
    "mutate.write": "mutate.write", "mutate.edit": "mutate.edit", "mutate.patch": "mutate.patch",
    "web.fetch": "web.fetch", "web.search": "web.search",
    "shell.run": "shell.run",
    "state.skills.load": "state.skills.load", "state.todos.write": "state.todos.write",
    "print": "print",
    "open": "raw.open",
    "threading.Thread": "raw.thread",
}


def dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def parse_code_features(code: str) -> dict:
    features: dict = {
        "chars": len(code),
        "lines": len(code.splitlines()),
        "parses": False,
        "has_run": False,
        "imports": [],
        "imports_agent": False,
        "imports_agents_top_level": False,
        "calls": [],
        "unique_calls": [],
        "modules": [],
        "uses_jobs": False,
        "uses_detached_task": False,
        "uses_foreground_task": False,
        "uses_browser": False,
        "uses_shell": False,
        "uses_mutate": False,
        "uses_fs": False,
        "uses_web": False,
        "uses_state": False,
        "uses_print": False,
        "uses_dir": False,
        "uses_a_tools": False,
        "uses_try": False,
        "uses_raw_open": False,
        "uses_raw_thread": False,
        "uses_subprocess": False,
        "uses_socket": False,
        "result_shape": None,
        "helper_functions": 0,
    }

    try:
        tree = ast.parse(code)
        features["parses"] = True
    except SyntaxError:
        return features

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "Run":
                features["has_run"] = True
            else:
                features["helper_functions"] += 1
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    features["imports"].append(alias.name)
                    if alias.name == "agent":
                        features["imports_agent"] = True
                    if alias.name == "agents":
                        features["imports_agents_top_level"] = True
            else:
                module = node.module or ""
                names = [alias.name for alias in node.names]
                features["imports"].append(module + ":" + ",".join(names))
                if module == "agent":
                    features["imports_agent"] = True
                    features["imports"][-1] = "agent:" + ",".join(names)
                    if "agents" in names:
                        features["imports_agents_top_level"] = True
        elif isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name:
                features["calls"].append(name)
        elif isinstance(node, ast.Try):
            features["uses_try"] = True
        elif isinstance(node, ast.Return):
            value = node.value
            if isinstance(value, ast.Dict):
                features["result_shape"] = "dict"
            elif isinstance(value, (ast.List, ast.Tuple)):
                features["result_shape"] = "list"
            elif isinstance(value, ast.Name):
                features["result_shape"] = "name"
            elif features["result_shape"] is None:
                features["result_shape"] = "other"

    text = code
    if re.search(r"\ba\.tools\b", text):
        features["uses_a_tools"] = True
    if re.search(r"\bdir\(", text):
        features["uses_dir"] = True
    if re.search(r"\bsubprocess\b", text):
        features["uses_subprocess"] = True
    if re.search(r"\bsocket\b", text):
        features["uses_socket"] = True

    normalized = []
    for call in features["calls"]:
        if call in KNOWN_CALLS:
            normalized.append(KNOWN_CALLS[call])
        elif call.startswith("agent.jobs."):
            normalized.append("jobs." + call.split(".", 2)[-1])
        elif call.startswith("jobs."):
            normalized.append(call)
        elif call.startswith("agents.tasks."):
            normalized.append(call)
        elif call.startswith("browser.page"):
            normalized.append("browser.page")
        elif call in TOOL_MODULES:
            normalized.append(call)
        elif call in {"dir", "len", "isinstance", "getattr", "str", "repr"}:
            normalized.append(call)
    features["unique_calls"] = sorted(set(normalized))
    features["calls"] = normalized

    for call in normalized:
        if call.startswith("fs."):
            features["uses_fs"] = True
        elif call.startswith("mutate."):
            features["uses_mutate"] = True
        elif call == "shell.run":
            features["uses_shell"] = True
        elif call.startswith("web."):
            features["uses_web"] = True
        elif call.startswith("state."):
            features["uses_state"] = True
        elif call.startswith("agents.tasks."):
            if call == "agents.tasks.start":
                features["uses_detached_task"] = True
            elif call == "agents.tasks.run":
                features["uses_foreground_task"] = True
        elif call.startswith("jobs."):
            features["uses_jobs"] = True
        elif call.startswith("browser."):
            features["uses_browser"] = True
        elif call == "print":
            features["uses_print"] = True
        elif call == "raw.open":
            features["uses_raw_open"] = True
        elif call == "raw.thread":
            features["uses_raw_thread"] = True

    features["modules"] = sorted({
        TOOL_MODULES[c] for c in normalized if c in TOOL_MODULES
    } | (
        {"jobs"} if features["uses_jobs"] else set()
    ))
    return features


def classify_program(features: dict, error: str | None) -> list[str]:
    tags: list[str] = []
    if error:
        tags.append("failed")
    if features["uses_dir"] or features["uses_a_tools"]:
        tags.append("probe")
    if features["uses_detached_task"]:
        tags.append("detached-task")
    if features["uses_jobs"]:
        tags.append("concurrent-jobs")
    if features["uses_browser"]:
        tags.append("browser")
    if features["uses_shell"] or features["uses_mutate"]:
        tags.append("build")
    if features["uses_fs"] or features["uses_web"] or features["uses_state"]:
        tags.append("read-or-verify")
    if features["uses_raw_thread"]:
        tags.append("raw-thread-fallback")
    if not tags:
        tags.append("other")
    return tags


def classify_error(message: str | None) -> str:
    if not message:
        return "none"
    lowered = message.lower()
    if "no module named" in lowered:
        return "import"
    if "has no attribute" in lowered:
        return "attribute"
    if "not iterable" in lowered or "object is not subscriptable" in lowered:
        return "shape-misuse"
    if "syntaxerror" in lowered or "outside function" in lowered or "invalid syntax" in lowered:
        return "syntax"
    if "timed out" in lowered:
        return "timeout"
    if "not enabled" in lowered or "unavailable" in lowered:
        return "unavailable"
    if "permission" in lowered:
        return "permission"
    return "other"


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def parse_transcript(path: Path):
    events = []
    if not path.exists():
        return events
    for line in path.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(event)
    return events


def summarize_run(path: Path):
    metrics = read_json(path / "metrics.json") or {}
    transcript = parse_transcript(path / "transcript.jsonl")
    session = read_json(path / "session.json") or {}

    name = path.name
    rel = path.relative_to(ROOT).as_posix()
    if "/arms/" in rel:
        arm = name.split("-", 1)[0]
        category = "arm"
        label = f"arm-{arm}"
        config = dict(ARM_CONFIG.get(arm, {}))
        capability = []
    elif "/scenarios/" in rel:
        base = name.rsplit("-", 1)[0]
        category = "scenario"
        label = base
        config = dict(SCENARIO_CONFIG.get(base, {}))
        arm = None
        capability = list(config.get("capability", []))
    else:
        category = "capability"
        base = name
        label = name
        config = {}
        arm = None
        capability = []

    python_calls = []
    direct_tools: Counter[str] = Counter()
    child_tools: Counter[str] = Counter()
    child_status: Counter[tuple[str, str]] = Counter()
    child_durations: dict[str, list[int]] = defaultdict(list)

    for event in transcript:
        part = event.get("part") or {}
        if part.get("type") != "tool":
            continue
        tool = part.get("tool", "")
        state = part.get("state") or {}
        direct_tools[tool] += 1
        metadata = state.get("metadata") or {}
        if tool == "python":
            code = (state.get("input") or {}).get("code", "")
            features = parse_code_features(code)
            message = metadata.get("message") if metadata.get("error") else None
            if not message and isinstance(state.get("output"), str) and state["output"].startswith("Python program failed"):
                message = state["output"].split("Python program failed:", 1)[-1].strip()
            calls = metadata.get("toolCalls") or []
            call_rows = []
            for call in calls:
                tool_name = call.get("tool", "")
                status = call.get("status", "")
                duration = call.get("durationMs", 0)
                child_tools[tool_name] += 1
                child_status[(tool_name, status)] += 1
                child_durations[tool_name].append(duration)
                call_rows.append(call)
            python_calls.append({
                "status": state.get("status"),
                "ok": not metadata.get("error", False),
                "error": message,
                "error_kind": classify_error(message),
                "duration_ms": (state.get("time") or {}).get("end", 0) - (state.get("time") or {}).get("start", 0),
                "child_calls": call_rows,
                "child_count": len(calls),
                "features": features,
                "tags": classify_program(features, message),
                "code": code,
            })

    python_ok = sum(1 for call in python_calls if call["ok"])
    python_failed = len(python_calls) - python_ok
    recovered = False
    for index, call in enumerate(python_calls[:-1]):
        if not call["ok"] and any(later["ok"] for later in python_calls[index + 1:]):
            recovered = True
            break

    prompt = None
    try:
        for message in session.get("messages", []):
            if message.get("info", {}).get("role") == "user":
                prompt = " ".join(
                    part.get("text", "")
                    for part in message.get("parts", [])
                    if part.get("type") == "text"
                ).strip()
                break
    except Exception:
        pass

    final_text = metrics.get("finalText") or ""
    verification_words = {
        "verified": bool(re.search(r"\bverif", final_text, re.I)),
        "read_back": bool(re.search(r"read[- ]?back|read the file back", final_text, re.I)),
        "limitation": bool(re.search(r"\blimitation\b|could not|couldn't|unable to", final_text, re.I)),
        "browser_check": bool(re.search(r"browser|chromium|cdp", final_text, re.I)),
        "static_check": bool(re.search(r"static|structure|balanced|syntax", final_text, re.I)),
    }

    tags: Counter[str] = Counter()
    for call in python_calls:
        tags.update(call["tags"])

    error_kinds: Counter[str] = Counter(call["error_kind"] for call in python_calls if not call["ok"])

    tool_module_usage: Counter[str] = Counter()
    for call in python_calls:
        for module in call["features"]["modules"]:
            tool_module_usage[module] += 1

    all_child = [call for item in python_calls for call in item["child_calls"]]
    child_duration_total = sum(call.get("durationMs", 0) for call in all_child)

    return {
        "id": name,
        "path": rel,
        "category": category,
        "label": label,
        "arm": arm,
        "capability": capability,
        "config": config,
        "prompt": prompt,
        "metrics": metrics,
        "session_title": (session.get("info") or {}).get("title"),
        "session_tokens": (session.get("info") or {}).get("tokens"),
        "python_calls": python_calls,
        "python_call_count": len(python_calls),
        "python_ok_count": python_ok,
        "python_failed_count": python_failed,
        "python_recovery": recovered,
        "python_success_rate": python_ok / len(python_calls) if python_calls else None,
        "direct_tools": dict(direct_tools),
        "child_tools": dict(child_tools),
        "child_status": {f"{tool}:{status}": count for (tool, status), count in child_status.items()},
        "child_duration_ms_total": child_duration_total,
        "child_duration_ms_by_tool": {key: sum(values) for key, values in child_durations.items()},
        "program_tags": dict(tags),
        "error_kinds": dict(error_kinds),
        "tool_module_usage": dict(tool_module_usage),
        "verification_words": verification_words,
        "final_text": final_text,
    }


def discover_runs() -> list[Path]:
    paths: list[Path] = []
    for pattern in ("arms/*", "scenarios/*/*", "2026-*"):
        paths.extend((ROOT / "harness" / "runs").glob(pattern))
    return sorted({path for path in paths if (path / "metrics.json").exists()})


def main() -> None:
    runs = [summarize_run(path) for path in discover_runs()]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs.json").write_text(json.dumps(runs, indent=2) + "\n")

    fieldnames = [
        "id", "category", "label", "python_call_count", "python_ok_count", "python_failed_count",
        "python_recovery", "python_success_rate", "child_call_count", "raw_open", "raw_exec", "raw_net",
        "errors", "duration_seconds", "input_tokens", "output_tokens", "reasoning_tokens",
        "cache_read_tokens", "files_changed", "verification", "limitation", "browser_check", "static_check",
    ]
    with (OUT / "runs.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for run in runs:
            metrics = run["metrics"] or {}
            tokens = metrics.get("tokens") or {}
            audit = metrics.get("audit") or {}
            verification = run["verification_words"]
            writer.writerow({
                "id": run["id"],
                "category": run["category"],
                "label": run["label"],
                "python_call_count": run["python_call_count"],
                "python_ok_count": run["python_ok_count"],
                "python_failed_count": run["python_failed_count"],
                "python_recovery": run["python_recovery"],
                "python_success_rate": run["python_success_rate"],
                "child_call_count": sum(run["child_tools"].values()),
                "raw_open": audit.get("rawOpen", 0),
                "raw_exec": audit.get("rawExec", 0),
                "raw_net": audit.get("rawNet", 0),
                "errors": metrics.get("errors"),
                "duration_seconds": metrics.get("durationSeconds"),
                "input_tokens": tokens.get("input"),
                "output_tokens": tokens.get("output"),
                "reasoning_tokens": tokens.get("reasoning"),
                "cache_read_tokens": (tokens.get("cache") or {}).get("read"),
                "files_changed": len(metrics.get("filesChanged") or []),
                "verification": verification["verified"],
                "limitation": verification["limitation"],
                "browser_check": verification["browser_check"],
                "static_check": verification["static_check"],
            })

    summary = {
        "runs": len(runs),
        "python_calls": sum(run["python_call_count"] for run in runs),
        "python_ok": sum(run["python_ok_count"] for run in runs),
        "python_failed": sum(run["python_failed_count"] for run in runs),
        "child_calls": sum(sum(run["child_tools"].values()) for run in runs),
        "child_tools": dict(sum((Counter(run["child_tools"]) for run in runs), Counter())),
        "tool_module_usage": dict(sum((Counter(run["tool_module_usage"]) for run in runs), Counter())),
        "program_tags": dict(sum((Counter(run["program_tags"]) for run in runs), Counter())),
        "error_kinds": dict(sum((Counter(run["error_kinds"]) for run in runs), Counter())),
        "verification_words": {
            key: sum(1 for run in runs if run["verification_words"][key])
            for key in ("verified", "read_back", "limitation", "browser_check", "static_check")
        },
        "raw_exec": sum((run["metrics"] or {}).get("audit", {}).get("rawExec", 0) for run in runs),
        "raw_open": sum((run["metrics"] or {}).get("audit", {}).get("rawOpen", 0) for run in runs),
        "raw_net": sum((run["metrics"] or {}).get("audit", {}).get("rawNet", 0) for run in runs),
        "durations": {
            run["id"]: (run["metrics"] or {}).get("durationSeconds")
            for run in runs
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
