"""Python code mode SDK for the manica-dei/opencode fork.

Model-written programs import narrow modules::

    from agent import fs, mutate, shell, web, state

The import is the capability. The SDK speaks newline-delimited JSON on fd 3
and writes its final envelope on fd 4. See ``spec/protocol.md``.
"""

from __future__ import annotations

import dataclasses
import math
import os
import platform
import socket
import sys
import threading
import traceback
from typing import Any, BinaryIO

from ._bridge import Bridge, PROTOCOL
from ._errors import AgentError
from . import jobs
from ._types import FetchResult, Image, Screenshot

__version__ = "0.1.0"

_ACTIVE_STACK: list["Client"] = []
_ACTIVE_LOCK = threading.Lock()


class Client:
    """Bridge client.

    In production the host passes a socketpair end as fd 3. Tests pass
    ``reader``/``writer`` directly. ``handshake`` exchanges the protocol hello
    and records the host's tool list and limits.
    """

    def __init__(
        self,
        *,
        reader: BinaryIO | None = None,
        writer: BinaryIO | None = None,
        handshake: bool = True,
        handshake_timeout: float = 30.0,
        call_timeout: float = 120.0,
    ) -> None:
        self._socket: socket.socket | None = None
        close_reader = True
        close_writer = True
        if reader is None or writer is None:
            if os.environ.get("AGENT_BRIDGE_TRANSPORT") == "stdio":
                import sys

                reader = sys.stdin.buffer
                writer = sys.stdout.buffer
                close_reader = False
                close_writer = False
            else:
                fd = int(os.environ.get("AGENT_BRIDGE_FD", "3"))
                self._socket = socket.socket(fileno=fd)
                reader = self._socket.makefile("rb")
                writer = self._socket.makefile("wb")

        self._bridge = Bridge(
            reader,
            writer,
            close_reader=close_reader,
            close_writer=close_writer,
        )
        self._call_timeout = call_timeout
        self.protocol: int | None = None
        self.tools: tuple[str, ...] = ()
        self.limits: dict[str, Any] = {}

        if handshake:
            try:
                self.handshake(timeout=handshake_timeout)
            except BaseException:
                self.close()
                raise

    def handshake(self, timeout: float = 30.0) -> None:
        self._bridge.send(
            {
                "type": "hello",
                "protocol": PROTOCOL,
                "sdk": __version__,
                "python": platform.python_version(),
            }
        )
        hello = self._bridge.wait_hello(timeout)
        protocol = hello.get("protocol")
        if protocol != PROTOCOL:
            raise AgentError("unavailable", f"bridge protocol {protocol} != {PROTOCOL}")
        self.protocol = protocol
        self.tools = tuple(str(item) for item in hello.get("tools", []))
        self.limits = dict(hello.get("limits", {}))

    def call(self, tool: str, input: dict[str, Any], timeout: float | None = None) -> Any:
        return self._bridge.call(
            tool,
            input,
            self._call_timeout if timeout is None else timeout,
        )

    def emit(self, message: dict[str, Any]) -> None:
        self._bridge.send(message)

    def __getattr__(self, name: str) -> Any:
        # Programs guess ``a.fs.read`` and ``a.jobs.start``; the modules are the
        # same objects the imports give.
        from ._program import MODULES

        if name in MODULES:
            import importlib

            return importlib.import_module(f"agent.{name}")
        raise AttributeError(
            f"'Client' object has no attribute {name!r}; "
            f"use a.tools, a.limits, or the modules {', '.join(MODULES)}"
        )

    def __enter__(self) -> "Client":
        _set_active(self)
        return self

    def __exit__(self, *exc: object) -> bool:
        _clear_active(self)
        self.close()
        return False

    def close(self) -> None:
        _clear_active(self)
        self._bridge.close()
        if self._socket is not None:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None


def _set_active(client: Client) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_STACK.append(client)


def _clear_active(client: Client) -> None:
    with _ACTIVE_LOCK:
        if _ACTIVE_STACK and _ACTIVE_STACK[-1] is client:
            _ACTIVE_STACK.pop()


def current_client() -> Client:
    with _ACTIVE_LOCK:
        if not _ACTIVE_STACK:
            raise AgentError(
                "unavailable",
                "no active agent.Client; call tools inside Run(ctx, a)",
            )
        return _ACTIVE_STACK[-1]


def to_json(value: Any, _path: str = "result", _seen: set[int] | None = None) -> Any:
    """Convert a program result into plain JSON data.

    Dataclasses, lists, tuples, dicts, and primitives are accepted. Anything
    else is a clear ``invalid_result`` error that names where the value sits.
    """

    if _seen is None:
        _seen = set()
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            raise AgentError(
                "invalid_result",
                f"non-finite float at {_path}; return a string, None, or a finite number",
            )
        return value
    if isinstance(value, Screenshot):
        return {
            "__agent_kind__": "screenshot",
            "path": value.path,
            "mime": value.mime,
            "data": value.data,
        }
    if isinstance(value, Image):
        return {
            "__agent_kind__": "attachment",
            "path": value.path,
            "mime": value.mime,
            "data": value.data,
        }
    if isinstance(value, FetchResult) and value.data:
        return {
            "__agent_kind__": "attachment",
            "path": value.url,
            "url": value.url,
            "mime": value.mime,
            "data": value.data,
            "text": value.text,
            "title": value.title,
        }
    if isinstance(value, (list, tuple)):
        marker = _enter(value, _path, _seen)
        try:
            return [to_json(item, f"{_path}[{index}]", _seen) for index, item in enumerate(value)]
        finally:
            _seen.remove(marker)
    if isinstance(value, dict):
        marker = _enter(value, _path, _seen)
        try:
            return {str(key): to_json(item, f"{_path}[{key!r}]", _seen) for key, item in value.items()}
        finally:
            _seen.remove(marker)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        skip = getattr(value, "_JSON_SKIP", ())
        data = {
            field.name: item
            for field in dataclasses.fields(value)
            if field.name not in skip
            for item in [getattr(value, field.name)]
            if item is not None
        }
        for name in getattr(value, "_JSON_EXTRA", ()):
            data[name] = getattr(value, name)
        marker = _enter(value, _path, _seen)
        try:
            return to_json(data, _path, _seen)
        finally:
            _seen.remove(marker)
    hint = {
        "set": "convert it with sorted(...) or list(...)",
        "frozenset": "convert it with sorted(...) or list(...)",
        "bytes": "decode it with .decode() or return a length or path instead",
        "bytearray": "decode it with .decode() or return a length or path instead",
    }.get(type(value).__name__, "return str, int, float, bool, None, list, dict, or a result object")
    raise AgentError("invalid_result", f"cannot serialize {type(value).__name__} at {_path}; {hint}")


def _enter(value: Any, path: str, seen: set[int] | None) -> int:
    """Track containers during serialization, including self-references."""

    if seen is None:
        raise AgentError("invalid_result", "internal serialization state is missing")
    marker = id(value)
    if marker in seen:
        raise AgentError("invalid_result", f"cyclic value at {path}")
    seen.add(marker)
    return marker


_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


def _trace(error: BaseException) -> str:
    """Render the frames of a failure that belong to the program, newest last.

    The SDK's own frames and the host harness are noise to the author of the
    program, so they are skipped. The line text comes from the program source.
    """

    frames = [
        frame
        for frame in traceback.extract_tb(error.__traceback__)
        if not os.path.abspath(frame.filename).startswith(_PACKAGE_DIR)
        and not frame.filename.endswith("zz_main.py")
    ][-6:]
    lines = []
    for frame in frames:
        name = os.path.basename(frame.filename)
        where = f'{name}:{frame.lineno} in {frame.name}'
        lines.append(f"  {where}: {frame.line}" if frame.line else f"  {where}")
    return "\n".join(lines)


def to_error(error: BaseException) -> dict[str, Any]:
    """Map an exception to the fd 4 error envelope.

    ``trace`` is present when the failure has frames from the program, so the
    model can see which line failed without a full Python traceback.
    """

    if isinstance(error, AgentError):
        body: dict[str, Any] = {
            "kind": error.kind,
            "message": error.message,
            "data": to_json(error.data) if error.data is not None else None,
        }
    else:
        body = {"kind": "exception", "message": f"{type(error).__name__}: {error}"}
    trace = _trace(error)
    if trace:
        body["trace"] = trace
    return body


def help(module: str | None = None) -> str:
    """Return a compact reference of the enabled SDK, or of one module."""

    from ._help import reference

    return reference(module)


from ._program import run_program  # noqa: E402  (after Client: the loader imports lazily)

# Make `from agent import agent` resolve to this package. Programs write that
# form as often as `import agent`.
agent = sys.modules[__name__]

__all__ = [
    "AgentError",
    "agent",
    "Client",
    "current_client",
    "help",
    "run_program",
    "jobs",
    "to_json",
    "to_error",
    "__version__",
]


def __dir__() -> list[str]:
    from ._program import MODULES

    return sorted({*__all__, *MODULES})
