#!/usr/bin/env python3
"""Sandbox integration host for the enuma-elis harness.

This is a deliberately small parent-side implementation of the fd 3/stdio
protocol. It launches the same bwrap shape the fork adapter uses, dispatches
the tool calls, and asserts that the sandbox and audit hook did their job.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

WORKSPACE = Path("/home/ubuntu/workspace")
RUNTIME = Path("/opt/manus/python/current")
PYTHON = RUNTIME / "bin" / "python3"
RUN_DIR = Path(os.environ.get("HOME", "/home/ubuntu")) / ".local/state/manus/python/harness"
SOURCE = Path("/opt/enuma/harness")


def resolve(value: str) -> Path:
    path = Path(value)
    path = (WORKSPACE / path) if not path.is_absolute() else path
    path = path.resolve()
    if not path.is_relative_to(WORKSPACE.resolve()):
        raise RuntimeError(f"path escapes workspace: {value}")
    return path


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(WORKSPACE))
    except ValueError:
        return str(path)


def handle(message: dict[str, Any]) -> Any:
    tool = message["tool"]
    data = message.get("input") or {}

    if tool == "fs.read":
        path = resolve(data["path"])
        text = path.read_text()
        return {
            "kind": "file",
            "path": relative(path),
            "text": text,
            "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
            "truncated": False,
        }

    if tool == "fs.glob":
        base = resolve(data.get("path", "."))
        entries = [
            {"path": relative(item), "type": "file"}
            for item in sorted(base.glob(data["pattern"]))
            if item.is_file()
        ]
        return {"entries": entries, "truncated": False}

    if tool == "mutate.write":
        path = resolve(data["path"])
        existed = path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data["content"])
        return {"file": relative(path), "bytes": len(data["content"]), "created": not existed}

    if tool == "mutate.edit":
        path = resolve(data["path"])
        text = path.read_text()
        old = data["old"]
        count = text.count(old)
        if count == 0:
            raise RuntimeError("oldString not found")
        next_text = text.replace(old, data["new"]) if data.get("replace_all") else text.replace(old, data["new"], 1)
        path.write_text(next_text)
        return {
            "file": relative(path),
            "replacements": count if data.get("replace_all") else 1,
            "additions": 0,
            "deletions": 0,
            "patch": "",
        }

    raise RuntimeError(f"unknown tool: {tool}")


def bwrap_args() -> list[str]:
    return [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--bind",
        str(WORKSPACE),
        str(WORKSPACE),
        "--ro-bind",
        str(RUN_DIR),
        "/tmp/agent",
        "--chdir",
        str(WORKSPACE),
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/local/bin:/usr/bin:/bin",
        "--setenv",
        "HOME",
        "/tmp/home",
        "--setenv",
        "TMPDIR",
        "/tmp",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--setenv",
        "LC_ALL",
        "C.UTF-8",
        "--setenv",
        "PYTHONUNBUFFERED",
        "1",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "PYTHONPATH",
        str(RUNTIME / "lib"),
        "--setenv",
        "AGENT_BRIDGE_TRANSPORT",
        "stdio",
        "--setenv",
        "AGENT_BRIDGE_FD",
        "1",
        "--",
        str(PYTHON),
        "/tmp/agent/zz_main.py",
    ]


def send(proc: subprocess.Popen[str], message: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    shutil.rmtree(RUN_DIR, ignore_errors=True)
    RUN_DIR.mkdir(parents=True)
    shutil.copy(SOURCE / "program.py", RUN_DIR / "program.py")
    shutil.copy(SOURCE / "zz_main.py", RUN_DIR / "zz_main.py")

    proc = subprocess.Popen(
        bwrap_args(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None

    stderr_lines: list[str] = []

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)

    threading.Thread(target=drain, daemon=True).start()

    audits: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None

    try:
        for line in proc.stdout:
            message = json.loads(line)
            kind = message.get("type")

            if kind == "hello":
                send(
                    proc,
                    {
                        "type": "hello",
                        "protocol": 1,
                        "tools": ["fs.read", "fs.glob", "mutate.edit", "mutate.write"],
                        "limits": {"calls": 20, "concurrency": 2},
                    },
                )
            elif kind == "call":
                try:
                    output = handle(message)
                    send(proc, {"type": "result", "id": message["id"], "ok": True, "output": output})
                except Exception as error:
                    send(
                        proc,
                        {
                            "type": "result",
                            "id": message["id"],
                            "ok": False,
                            "error": {"kind": "tool_failed", "message": str(error)},
                        },
                    )
            elif kind == "audit":
                audits.append(message)
            elif kind == "final":
                final = message
                break
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    check(final is not None, f"no final envelope; stderr:\n{''.join(stderr_lines)}")
    check(final["ok"], f"program failed: {final.get('error')}")

    value = final["value"]
    check(value["text"].startswith("# enuma-elis harness"), "read returned the wrong file")
    check(value["globbed"] == ["sample.txt"], f"unexpected glob: {value['globbed']}")
    check(value["edited"] == "sample.txt", f"unexpected edit target: {value['edited']}")
    check(value["written"] == len("written by mutate\n"), "write byte count is wrong")
    check(value["raw_ok"] is True, "raw workspace write was blocked")
    check(value["system_blocked"] is True, "system write was not blocked")

    check((WORKSPACE / "out.txt").read_text() == "written by mutate\n", "mutate.write did not land")
    check((WORKSPACE / "raw.txt").read_text() == "raw\n", "raw write did not land")
    check((WORKSPACE / "sample.txt").read_text().startswith("DONE:"), "mutate.edit did not land")
    check(not Path("/etc/enuma-harness").exists(), "/etc was writable")

    raw_opens = {
        str(event.get("path"))
        for event in audits
        if event.get("kind") == "raw_open"
    }
    check(any(path.endswith("raw.txt") for path in raw_opens), f"raw workspace open not audited: {raw_opens}")
    check("/etc/enuma-harness" in raw_opens, f"system open not audited: {raw_opens}")

    print("HARNESS OK")
    print(json.dumps(value, indent=2))
    print(json.dumps(audits, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as error:
        print(f"HARNESS FAILED: {error}", file=sys.stderr)
        sys.exit(1)
