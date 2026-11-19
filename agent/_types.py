"""Typed tool results.

The host returns plain JSON; the SDK turns it into dataclasses. Each parser is
deliberately forgiving about absent optional fields and strict about the shape
of the fields it needs.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Union

from ._errors import AgentError


def _object(value: Any, tool: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AgentError("invalid_output", f"{tool} returned a non-object")
    return value


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


# Names models guess that mean a field with another name.
_SYNONYMS = {
    "files": "paths",
    "filenames": "paths",
    "content": "text",
    "contents": "text",
    "body": "text",
    "stdout": "output",
    "code": "exit",
    "status_code": "exit",
    "mimetype": "mime",
    "content_type": "mime",
    "size": "bytes",
    "count": "lines",
}


class _Result:
    """Dict-style access for result objects.

    Programs reach for ``result["path"]`` and ``result.get("mime")`` as often as
    for attributes, so both work. A wrong name lists the real ones.
    """

    _JSON_SKIP: tuple[str, ...] = ()

    @classmethod
    def _names(cls) -> list[str]:
        own = [field.name for field in fields(cls)] if is_dataclass(cls) else []
        props = [
            name
            for name in dir(cls)
            if not name.startswith("_") and isinstance(getattr(cls, name, None), property)
        ]
        return [*own, *props]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        names = type(self)._names()
        close = difflib.get_close_matches(name, names, n=1)
        if not close:
            close = [_SYNONYMS[name]] if _SYNONYMS.get(name) in names else []
        hint = f"; did you mean {close[0]!r}?" if close else ""
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}{hint} "
            f"Fields: {', '.join(names)}"
        )

    def __getitem__(self, key: str) -> Any:
        if isinstance(key, str) and key in type(self)._names():
            return getattr(self, key)
        raise KeyError(f"{key!r}; {type(self).__name__} fields: {', '.join(type(self)._names())}")

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self) -> list[str]:
        return type(self)._names()

    def items(self) -> list[tuple[str, Any]]:
        return [(name, getattr(self, name)) for name in self.keys()]

    def values(self) -> list[Any]:
        return [getattr(self, name) for name in self.keys()]


# --- filesystem read -------------------------------------------------------


@dataclass(frozen=True)
class DirEntry(_Result):
    name: str
    type: str


@dataclass(frozen=True)
class Text(_Result):
    path: str
    text: str
    lines: int | None = None
    truncated: bool = False
    kind: str = "file"
    next_offset: int | None = None

    @property
    def total_lines(self) -> int | None:
        """Alias for :attr:`lines`, for callers that expect that name."""

        return self.lines


@dataclass(frozen=True)
class Image(_Result):
    path: str
    mime: str
    data: str
    truncated: bool = False
    kind: str = "image"

    @property
    def bytes(self) -> bytes:
        """Decode a native binary attachment, when present."""

        if not self.data:
            return b""
        import base64

        return base64.b64decode(self.data)


@dataclass(frozen=True)
class Directory(_Result):
    path: str
    entries: tuple[DirEntry, ...]
    truncated: bool = False
    kind: str = "directory"
    total: int | None = None

    @property
    def names(self) -> tuple[str, ...]:
        """Entry names, without the directory type."""

        return tuple(entry.name for entry in self.entries)

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)


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
                next_offset=value.get("next_offset"),
            )
        if kind in ("image", "attachment"):
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
                total=value.get("total"),
            )
    except (KeyError, TypeError, ValueError) as error:
        raise AgentError("invalid_output", f"malformed read output: {error}") from error

    raise AgentError("invalid_output", f"unknown read kind: {kind}")


# --- filesystem search -----------------------------------------------------


@dataclass(frozen=True)
class FileEntry(_Result):
    path: str
    type: str = "file"


@dataclass(frozen=True)
class GlobResult(_Result):
    entries: tuple[FileEntry, ...]
    truncated: bool = False

    @property
    def paths(self) -> tuple[str, ...]:
        """Convenience view of the matching paths."""

        return tuple(entry.path for entry in self.entries)

    def __iter__(self):
        """Iterate over entries, so callers do not iterate the result object by mistake."""

        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)


@dataclass(frozen=True)
class GrepMatch(_Result):
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class GrepResult(_Result):
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
class EditResult(_Result):
    file: str
    replacements: int
    additions: int
    deletions: int
    patch: str = ""


@dataclass(frozen=True)
class WriteResult(_Result):
    file: str
    bytes: int
    created: bool


@dataclass(frozen=True)
class PatchResult(_Result):
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
class ShellResult(_Result):
    exit: int
    stdout: str
    stderr: str
    output: str
    truncated: bool = False
    timed_out: bool = False
    output_path: str | None = None

    # stdout and stderr are merged in ``output``; keep them out of JSON.
    _JSON_SKIP = ("stdout", "stderr")

    @property
    def exit_code(self) -> int:
        """Alias for :attr:`exit`, for callers that expect that name."""

        return self.exit

    @property
    def returncode(self) -> int:
        """Alias for :attr:`exit`, matching ``subprocess``."""

        return self.exit

    @property
    def ok(self) -> bool:
        """True when the command exited with 0."""

        return self.exit == 0


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
class FetchResult(_Result):
    url: str
    text: str
    title: str = ""
    truncated: bool = False
    kind: str = "text"
    mime: str = ""
    data: str = ""

    @property
    def bytes(self) -> bytes:
        """Decode a native binary attachment, when present."""

        if not self.data:
            return b""
        import base64

        return base64.b64decode(self.data)


@dataclass(frozen=True)
class SearchResult(_Result):
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
        kind=str(value.get("kind", "text")),
        mime=str(value.get("mime", "")),
        data=str(value.get("data", "")),
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
class Skill(_Result):
    name: str
    directory: str
    content: str


@dataclass(frozen=True)
class Todo(_Result):
    content: str
    status: str
    priority: str


@dataclass(frozen=True)
class Screenshot(_Result):
    path: str
    mime: str = "image/png"
    data: str = ""

    @property
    def bytes(self) -> bytes:
        """Decode the host-provided base64 image, when present."""

        if not self.data:
            return b""
        import base64

        return base64.b64decode(self.data)


@dataclass(frozen=True)
class TaskResult(_Result):
    session_id: str
    output: str
    transcript_path: str | None = None
    background: bool = False
    model: str | None = None


@dataclass(frozen=True)
class TaskJob(_Result):
    session_id: str
    job_id: str
    description: str = ""
    status: str = "running"
    background: bool = True
    model: str | None = None


def parse_screenshot(data: Any) -> Screenshot:
    value = _object(data, "screenshot")
    path = value.get("path") or value.get("text") or ""
    return Screenshot(
        path=str(path),
        mime=str(value.get("mime", "image/png")),
        data=str(value.get("data", "")),
    )


def parse_task(data: Any) -> TaskResult:
    value = _object(data, "task")
    return TaskResult(
        session_id=str(value.get("session_id", "")),
        output=str(value.get("output", "")),
        transcript_path=str(value["transcript_path"]) if value.get("transcript_path") else None,
        background=bool(value.get("background", False)),
        model=str(value["model"]) if value.get("model") else None,
    )


def parse_task_job(data: Any) -> TaskJob:
    value = _object(data, "task_job")
    return TaskJob(
        session_id=str(value.get("session_id", "")),
        job_id=str(value.get("job_id", value.get("session_id", ""))),
        description=str(value.get("description", "")),
        status=str(value.get("status", "running")),
        background=bool(value.get("background", True)),
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
