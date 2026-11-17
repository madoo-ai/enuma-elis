"""Filesystem mutation tools: edit, write, patch."""

from __future__ import annotations

from typing import Any

from . import current_client
from ._types import EditResult, PatchResult, WriteResult, parse_edit, parse_patch, parse_write


def edit(path: str, old: str, new: str, replace_all: bool = False) -> EditResult:
    """Replace exact text in one file and return the applied diff."""

    payload: dict[str, Any] = {"path": path, "old": old, "new": new}
    if replace_all:
        payload["replace_all"] = True
    return parse_edit(current_client().call("mutate.edit", payload))


def write(path: str, content: str) -> WriteResult:
    """Write one file, creating it when absent."""

    return parse_write(current_client().call("mutate.write", {"path": path, "content": content}))


def patch(text: str) -> PatchResult:
    """Apply a patch document and return the changed files."""

    return parse_patch(current_client().call("mutate.patch", {"text": text}))


__all__ = ["edit", "write", "patch"]
