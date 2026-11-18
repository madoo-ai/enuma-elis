"""Typed tool results.

The host returns plain JSON; the SDK turns it into dataclasses. Each parser is
deliberately forgiving about absent optional fields and strict about the shape
of the fields it needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

from ._errors import AgentError


def _object(value: Any, tool: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentError("invalid_output", f"{tool} returned a non-object")
    return value


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


# --- filesystem read -------------------------------------------------------


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
    value = _object(data, "read")
    try:
        kind = value.get("kind", "file")
        if kind == "file":
            return Text(
                path=str(value["path"]),
                text=str(value.get("text", "")),
                lines=value.get("lines"),
                truncated=bool(value.get("truncated", False)),
            )
        if kind == "image":
            return Image(
                path=str(value["path"]),
                mime=str(value.get("mime", "application/octet-stream")),
                data=str(value.get("data", "")),
                truncated=bool(value.get("truncated", False)),
            )
        if kind == "directory":
            entries = tuple(
                DirEntry(name=str(entry.get("name", "")), type=str(entry.get("type", "file")))
                for entry in value.get("entries", [])
                if isinstance(entry, dict)
            )
            return Directory(
                path=str(value["path"]),
                entries=entries,
                truncated=bool(value.get("truncated", False)),
            )
    except (KeyError, TypeError, ValueError) as error:
        raise AgentError("invalid_output", f"malformed read output: {error}") from error

    raise AgentError("invalid_output", f"unknown read kind: {kind}")


# --- filesystem search -----------------------------------------------------


@dataclass(frozen=True)
class FileEntry:
    path: str
    type: str = "file"


@dataclass(frozen=True)
class GlobResult:
    entries: tuple[FileEntry, ...]
    truncated: bool = False


@dataclass(frozen=True)
class GrepMatch:
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class GrepResult:
    matches: tuple[GrepMatch, ...]
    truncated: bool = False


def parse_glob(data: Any) -> GlobResult:
    if isinstance(data, list):
        entries = data
        truncated = False
    else:
        value = _object(data, "glob")
        entries = value.get("entries", [])
        truncated = bool(value.get("truncated", False))
    return GlobResult(
        entries=tuple(
            FileEntry(path=str(entry.get("path", "")), type=str(entry.get("type", "file")))
            for entry in entries
            if isinstance(entry, dict)
        ),
        truncated=truncated,
    )


def parse_grep(data: Any) -> GrepResult:
    if isinstance(data, list):
        rows = data
        truncated = False
    else:
        value = _object(data, "grep")
        rows = value.get("matches", [])
        truncated = bool(value.get("truncated", False))
    return GrepResult(
        matches=tuple(
            GrepMatch(path=str(row.get("path", "")), line=int(row.get("line", 0)), text=str(row.get("text", "")))
            for row in rows
            if isinstance(row, dict)
        ),
        truncated=truncated,
    )


# --- filesystem mutation ---------------------------------------------------


@dataclass(frozen=True)
class EditResult:
    file: str
    replacements: int
    additions: int
    deletions: int
    patch: str = ""


@dataclass(frozen=True)
class WriteResult:
    file: str
    bytes: int
    created: bool


@dataclass(frozen=True)
class PatchResult:
    files: tuple[str, ...]
    diff: str = ""


def parse_edit(data: Any) -> EditResult:
    value = _object(data, "edit")
    return EditResult(
        file=str(value.get("file", "")),
        replacements=int(value.get("replacements", 0)),
        additions=int(value.get("additions", 0)),
        deletions=int(value.get("deletions", 0)),
        patch=str(value.get("patch", "")),
    )


def parse_write(data: Any) -> WriteResult:
    value = _object(data, "write")
    return WriteResult(
        file=str(value.get("file", "")),
        bytes=int(value.get("bytes", 0)),
        created=bool(value.get("created", False)),
    )


def parse_patch(data: Any) -> PatchResult:
    value = _object(data, "patch")
    files = value.get("files", [])
    return PatchResult(
        files=tuple(str(item) for item in files),
        diff=str(value.get("diff", "")),
    )


# --- process ---------------------------------------------------------------


@dataclass(frozen=True)
class ShellResult:
    exit: int
    stdout: str
    stderr: str
    output: str
    truncated: bool = False
    timed_out: bool = False
    output_path: str | None = None


def parse_shell(data: Any) -> ShellResult:
    value = _object(data, "shell")
    return ShellResult(
        exit=int(value.get("exit", 0)),
        stdout=str(value.get("stdout", "")),
        stderr=str(value.get("stderr", "")),
        output=str(value.get("output", "")),
        truncated=bool(value.get("truncated", False)),
        timed_out=bool(value.get("timed_out", False)),
        output_path=str(value["output_path"]) if value.get("output_path") else None,
    )


# --- network ---------------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    url: str
    text: str
    title: str = ""
    truncated: bool = False


@dataclass(frozen=True)
class SearchResult:
    query: str
    text: str
    provider: str = ""


def parse_fetch(data: Any) -> FetchResult:
    value = _object(data, "fetch")
    return FetchResult(
        url=str(value.get("url", "")),
        text=str(value.get("text", "")),
        title=str(value.get("title", "")),
        truncated=bool(value.get("truncated", False)),
    )


def parse_search(data: Any) -> SearchResult:
    value = _object(data, "search")
    return SearchResult(
        query=str(value.get("query", "")),
        text=str(value.get("text", "")),
        provider=str(value.get("provider", "")),
    )


# --- session state ---------------------------------------------------------


@dataclass(frozen=True)
class Skill:
    name: str
    directory: str
    content: str


@dataclass(frozen=True)
class Todo:
    content: str
    status: str
    priority: str


@dataclass(frozen=True)
class TaskResult:
    session_id: str
    output: str
    transcript_path: str | None = None
    background: bool = False
    model: str | None = None


def parse_task(data: Any) -> TaskResult:
    value = _object(data, "task")
    return TaskResult(
        session_id=str(value.get("session_id", "")),
        output=str(value.get("output", "")),
        transcript_path=str(value["transcript_path"]) if value.get("transcript_path") else None,
        background=bool(value.get("background", False)),
        model=str(value["model"]) if value.get("model") else None,
    )


def parse_skill(data: Any) -> Skill:
    value = _object(data, "skill")
    return Skill(
        name=str(value.get("name", "")),
        directory=str(value.get("directory", "")),
        content=str(value.get("content", "")),
    )


def parse_todos(data: Any) -> tuple[Todo, ...]:
    rows = data.get("todos", []) if isinstance(data, dict) else data
    return tuple(
        Todo(
            content=str(row.get("content", "")),
            status=str(row.get("status", "pending")),
            priority=str(row.get("priority", "medium")),
        )
        for row in _list(rows)
        if isinstance(row, dict)
    )
