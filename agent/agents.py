"""Subagent tasks."""

from __future__ import annotations

from typing import Any

from . import current_client
from ._errors import AgentError
from ._types import TaskResult, parse_task


class _Tasks:
    def run(
        self,
        type: str,
        prompt: str,
        description: str | None = None,
        background: bool = False,
    ) -> TaskResult:
        """Run one subagent and return its final output.

        Background mode is not available in Python code mode; the host would
        return immediately with no result, which is not useful inside a program.
        """

        if background:
            raise AgentError("unavailable", "background tasks are not supported in python mode")

        payload: dict[str, Any] = {
            "type": type,
            "prompt": prompt,
            "description": description or "python task",
        }
        return parse_task(current_client().call("agents.tasks.run", payload))


tasks = _Tasks()

__all__ = ["tasks"]
