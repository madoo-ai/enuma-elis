"""Process execution."""

from __future__ import annotations

import shlex
from typing import Any

from . import current_client
from ._errors import AgentError
from ._types import ShellResult, parse_shell


def run(
    command: str | list[str],
    workdir: str | None = None,
    timeout: int | None = None,
    check: bool = False,
) -> ShellResult:
    """Run one shell command through the host.

    ``command`` is a shell string, or an argv list that is quoted for you, so
    ``run(["git", "commit", "-m", message])`` needs no escaping. ``timeout`` is
    milliseconds. ``check=True`` raises :class:`AgentError` on a nonzero exit;
    the default returns the result for inspection.
    """

    if isinstance(command, (list, tuple)):
        command = shlex.join(str(part) for part in command)

    payload: dict[str, Any] = {"command": command}
    if workdir is not None:
        payload["workdir"] = workdir
    if timeout is not None:
        payload["timeout"] = timeout
    result = parse_shell(current_client().call("shell.run", payload))
    if check and (result.exit != 0 or result.timed_out):
        kind = "timeout" if result.timed_out else "tool_failed"
        message = (
            f"command timed out: {command}"
            if result.timed_out
            else f"command exited with {result.exit}: {command}"
        )
        raise AgentError(kind, message, {"exit": result.exit, "output": result.output, "timed_out": result.timed_out})
    return result


__all__ = ["run"]


def __dir__() -> list[str]:
    return sorted(__all__)
