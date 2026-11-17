"""Session state: skills and todos."""

from __future__ import annotations

import dataclasses
from typing import Any

from . import current_client
from ._types import Skill, Todo, parse_skill, parse_todos


class _Skills:
    def load(self, name: str) -> Skill:
        return parse_skill(current_client().call("state.skills.load", {"name": name}))


class _Todos:
    def write(self, todos: list[Todo] | list[dict[str, Any]]) -> tuple[Todo, ...]:
        items = [
            item if isinstance(item, dict) else dataclasses.asdict(item)
            for item in todos
        ]
        return parse_todos(current_client().call("state.todos.write", {"todos": items}))


skills = _Skills()
todos = _Todos()

__all__ = ["skills", "todos"]
