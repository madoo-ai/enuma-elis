"""Process execution."""

from __future__ import annotations

from typing import Any

from . import current_client
from ._errors import AgentError
from ._types import ShellResult, parse_shell


def run(
    command: str,
    workdir: str | None = None,
    timeout: int | None = None,
    check: bool = False,
) -> ShellResult:
    """Run one shell command through the host.

    ``timeout`` is milliseconds. ``check=True`` raises :class:`AgentError` on a
    nonzero exit; the default returns the result for inspection.
    """

    payload: dict[str, Any] = {"command": command}
    if workdir is not None:
        payload["workdir"] = workdir
    if timeout is not None:
        payload["timeout"] = timeout
    result = parse_shell(current_client().call("shell.run", payload))
    if check and result.exit != 0:
        raise AgentError(
            "tool_failed",
            f"command exited with {result.exit}: {command}",
            {"exit": result.exit, "output": result.output},
        )
    return result


__all__ = ["run"]
