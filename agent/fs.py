"""Read-only filesystem tools.

Phase 0 implements ``read``. ``glob`` and ``grep`` land with the manifest
generator; their signatures are documented in ``python-tool-library.md``.
"""

from __future__ import annotations

from typing import Any

from . import current_client
from ._types import ReadResult, parse_read


def read(path: str, offset: int | None = None, limit: int | None = None) -> ReadResult:
    """Read a file, an image, or a page of a directory through the host."""

    payload: dict[str, Any] = {"path": path}
    if offset is not None:
        payload["offset"] = offset
    if limit is not None:
        payload["limit"] = limit
    return parse_read(current_client().call("fs.read", payload))


__all__ = ["read"]
