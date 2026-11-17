"""Typed read results.

The host returns JSON; the SDK turns it into the same tagged shapes the tool
manifest declares. ``fs.read`` returns one of ``Text``, ``Image``, or
``Directory``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

from ._errors import AgentError


@dataclass(frozen=True)
class DirEntry:
    name: str
    type: str


@dataclass(frozen=True)
class Text:
    path: str
    text: str
    lines: int | None = None
    truncated: bool = False
    kind: str = "file"


@dataclass(frozen=True)
class Image:
    path: str
    mime: str
    data: str
    truncated: bool = False
    kind: str = "image"


@dataclass(frozen=True)
class Directory:
    path: str
    entries: tuple[DirEntry, ...]
    truncated: bool = False
    kind: str = "directory"


ReadResult = Union[Text, Image, Directory]


def parse_read(data: Any) -> ReadResult:
    if not isinstance(data, dict):
        raise AgentError("invalid_output", "read returned a non-object")

    try:
        kind = data.get("kind", "file")
        if kind == "file":
            return Text(
                path=str(data["path"]),
                text=str(data.get("text", "")),
                lines=data.get("lines"),
                truncated=bool(data.get("truncated", False)),
            )
        if kind == "image":
            return Image(
                path=str(data["path"]),
                mime=str(data.get("mime", "application/octet-stream")),
                data=str(data.get("data", "")),
                truncated=bool(data.get("truncated", False)),
            )
        if kind == "directory":
            entries = tuple(
                DirEntry(name=str(entry.get("name", "")), type=str(entry.get("type", "file")))
                for entry in data.get("entries", [])
                if isinstance(entry, dict)
            )
            return Directory(
                path=str(data["path"]),
                entries=entries,
                truncated=bool(data.get("truncated", False)),
            )
    except (KeyError, TypeError, ValueError) as error:
        raise AgentError("invalid_output", f"malformed read output: {error}") from error

    raise AgentError("invalid_output", f"unknown read kind: {kind}")
