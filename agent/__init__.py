"""Python code mode SDK for the manica-dei/opencode fork.

Model-written programs import narrow modules::

    from agent import fs, mutate, shell, web, state

The import is the capability. The SDK speaks newline-delimited JSON on fd 3
and writes its final envelope on fd 4. See ``spec/protocol.md``.
"""

from __future__ import annotations

import dataclasses
import os
import platform
import socket
import threading
from typing import Any, BinaryIO

from ._bridge import Bridge, PROTOCOL
from ._errors import AgentError

__version__ = "0.1.0"

_ACTIVE: "Client | None" = None
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
    global _ACTIVE
    with _ACTIVE_LOCK:
        _ACTIVE = client


def _clear_active(client: Client) -> None:
    global _ACTIVE
    with _ACTIVE_LOCK:
        if _ACTIVE is client:
            _ACTIVE = None


def current_client() -> Client:
    with _ACTIVE_LOCK:
        if _ACTIVE is None:
            raise AgentError("unavailable", "no active agent.Client")
        return _ACTIVE


def to_json(value: Any) -> Any:
    """Convert a program result into plain JSON data.

    Dataclasses, lists, tuples, dicts, and primitives are accepted. Anything
    else is a clear ``invalid_result`` error instead of a stack trace.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [to_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_json(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_json(dataclasses.asdict(value))
    raise AgentError("invalid_result", f"cannot serialize {type(value).__name__}")


def to_error(error: BaseException) -> dict[str, Any]:
    """Map an exception to the fd 4 error envelope."""

    if isinstance(error, AgentError):
        return {
            "kind": error.kind,
            "message": error.message,
            "data": to_json(error.data) if error.data is not None else None,
        }
    return {"kind": "tool_failed", "message": str(error)}


__all__ = [
    "AgentError",
    "Client",
    "current_client",
    "to_json",
    "to_error",
    "__version__",
]
