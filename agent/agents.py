"""Subagent tasks.

``tasks.run`` is foreground: the program waits for the child and gets its final
output. ``tasks.start`` is detached: the program returns immediately, and the
host notifies the session when the child finishes.
"""

from __future__ import annotations

from typing import Any

from . import current_client
from ._errors import AgentError
from ._types import TaskJob, TaskResult, parse_task, parse_task_job


class _Tasks:
    def run(
        self,
        type: str,
        prompt: str,
        description: str | None = None,
        background: bool = False,
    ) -> TaskResult:
        """Run one subagent and return its final output.

        Use :meth:`start` for detached work. A background ``run`` would return
        immediately with no useful value inside a program.
        """

        if background:
            raise AgentError("unavailable", "use agents.tasks.start for detached subagents")

        payload: dict[str, Any] = {
            "type": type,
            "prompt": prompt,
            "description": description or "python task",
        }
        return parse_task(current_client().call("agents.tasks.run", payload))

    def start(
        self,
        type: str,
        prompt: str,
        description: str | None = None,
    ) -> TaskJob:
        """Start one detached subagent and return its job handle.

        The host notifies the session when the child finishes; the program does
        not wait for it. This counts against the task budget.
        """

        payload: dict[str, Any] = {
            "type": type,
            "prompt": prompt,
            "description": description or "python task",
        }
        return parse_task_job(current_client().call("agents.tasks.start", payload))


tasks = _Tasks()

__all__ = ["tasks"]
