"""Error values returned by the bridge.

The host maps tool failures to one of the kinds below. Programs can inspect
them instead of parsing strings::

    from agent import AgentError

    try:
        fs.read("missing.go")
    except AgentError as error:
        if error.kind == "not_found":
            ...
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AgentError(Exception):
    kind: str
    message: str
    data: Any = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"
