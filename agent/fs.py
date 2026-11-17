"""Read-only filesystem tools: read, glob, grep."""

from __future__ import annotations

from typing import Any

from . import current_client
from ._types import GlobResult, GrepResult, ReadResult, parse_glob, parse_grep, parse_read


def read(path: str, offset: int | None = None, limit: int | None = None) -> ReadResult:
    """Read a file, an image, or a page of a directory through the host."""

    payload: dict[str, Any] = {"path": path}
    if offset is not None:
        payload["offset"] = offset
    if limit is not None:
        payload["limit"] = limit
    return parse_read(current_client().call("fs.read", payload))


def glob(pattern: str, path: str | None = None, limit: int | None = None) -> GlobResult:
    """Find files by glob pattern within the workspace."""

    payload: dict[str, Any] = {"pattern": pattern}
    if path is not None:
        payload["path"] = path
    if limit is not None:
        payload["limit"] = limit
    return parse_glob(current_client().call("fs.glob", payload))


def grep(
    pattern: str,
    path: str | None = None,
    include: str | None = None,
    limit: int | None = None,
) -> GrepResult:
    """Search file contents by regular expression."""

    payload: dict[str, Any] = {"pattern": pattern}
    if path is not None:
        payload["path"] = path
    if include is not None:
        payload["include"] = include
    if limit is not None:
        payload["limit"] = limit
    return parse_grep(current_client().call("fs.grep", payload))


__all__ = ["read", "glob", "grep"]
