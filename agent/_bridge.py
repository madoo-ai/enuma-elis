"""fd 3 bridge: handshake, calls, results, audit.

The host reserves fd 3 for the duplex call stream and fd 4 for the final
envelope. This module owns the line framing, the reader thread, and the
pending-call table. See ``spec/protocol.md``.
"""

from __future__ import annotations

import itertools
import json
import os
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeout
from typing import Any, BinaryIO

from ._errors import AgentError

PROTOCOL = 1

# Shared by the call writer and the sitecustomize audit hook. Both write to
# fd 3; the lock keeps JSON lines from interleaving.
_LOCK = threading.Lock()
_FD = int(os.environ.get("AGENT_BRIDGE_FD", "3"))


def _encode(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")


def write_line(writer: BinaryIO, message: dict[str, Any]) -> None:
    data = _encode(message)
    with _LOCK:
        writer.write(data)
        writer.flush()


def emit(message: dict[str, Any]) -> None:
    """Write one audit line without a Client.

    Outside code mode there is no bridge fd; the write is ignored so a plain
    ``python3 program.py`` does not crash in ``sitecustomize``.
    """

    data = _encode(message)
    with _LOCK:
        try:
            os.write(_FD, data)
        except OSError:
            pass


class Bridge:
    """Reader thread + pending calls over a duplex stream."""

    def __init__(
        self,
        reader: BinaryIO,
        writer: BinaryIO,
        *,
        close_reader: bool = True,
        close_writer: bool = True,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._close_reader = close_reader
        self._close_writer = close_writer
        self._pending: dict[str, Future[Any]] = {}
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._hello: dict[str, Any] | None = None
        self._hello_event = threading.Event()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="agent-bridge", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            while True:
                line = self._reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                kind = message.get("type")
                if kind == "hello":
                    self._hello = message
                    self._hello_event.set()
                elif kind == "result":
                    with self._lock:
                        future = self._pending.pop(message.get("id"), None)
                    if future is None or future.done():
                        continue
                    if message.get("ok"):
                        future.set_result(message.get("output"))
                    else:
                        error = message.get("error") or {}
                        future.set_exception(
                            AgentError(
                                str(error.get("kind", "tool_failed")),
                                str(error.get("message", "tool failed")),
                                error.get("data"),
                            )
                        )
        except (OSError, ValueError):
            pass
        finally:
            self._fail_all(AgentError("canceled", "bridge closed"))
            if self._close_reader:
                try:
                    self._reader.close()
                except OSError:
                    pass

    def _fail_all(self, error: AgentError) -> None:
        self._closed = True
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(error)
        # Unblock a handshake waiter; it checks whether hello actually arrived.
        self._hello_event.set()

    def send(self, message: dict[str, Any]) -> None:
        if self._closed:
            raise AgentError("canceled", "bridge closed")
        try:
            write_line(self._writer, message)
        except (OSError, ValueError) as error:
            # A close can race a write. Report it as a closed bridge rather
            # than letting the caller see a raw I/O error.
            self._fail_all(AgentError("canceled", "bridge closed during write"))
            raise AgentError("canceled", f"bridge closed during write: {error}") from error

    def wait_hello(self, timeout: float) -> dict[str, Any]:
        if not self._hello_event.wait(timeout):
            raise AgentError("timeout", "handshake timed out")
        if self._hello is None:
            raise AgentError("canceled", "bridge closed before handshake")
        return self._hello

    def call(self, tool: str, input: dict[str, Any], timeout: float) -> Any:
        if self._closed:
            raise AgentError("canceled", "bridge closed")

        call_id = f"c{next(self._ids)}"
        future: Future[Any] = Future()
        with self._lock:
            self._pending[call_id] = future

        try:
            self.send({"type": "call", "id": call_id, "tool": tool, "input": input})
            return future.result(timeout=timeout)
        except FutureTimeout:
            with self._lock:
                self._pending.pop(call_id, None)
            try:
                self.send({"type": "cancel", "id": call_id})
            except AgentError:
                pass
            raise AgentError("timeout", f"{tool} timed out after {timeout:g}s")
        except AgentError:
            raise
        except Exception as error:  # defensive: bridge failures are tool failures
            raise AgentError("tool_failed", str(error)) from error

    def close(self) -> None:
        self._fail_all(AgentError("canceled", "bridge closed"))
        # Do not close the reader here: the reader thread may be blocked in
        # readline, and BufferedReader.close() waits for that lock. The owner
        # shuts down the socket, which unblocks the thread; the thread closes
        # the reader in its finally block.
        if self._close_writer:
            try:
                self._writer.close()
            except OSError:
                pass
