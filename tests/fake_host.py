"""A tiny host for SDK tests.

It speaks the same fd 3 protocol as the fork adapter over a socketpair. No
TypeScript, no bwrap, no real tools.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any, Callable

from agent import Client

Handler = Callable[[dict[str, Any]], Any]


class FakeHost:
    def __init__(self, handlers: dict[str, Handler] | None = None) -> None:
        self.client_sock, self.host_sock = socket.socketpair()
        self.client_reader = self.client_sock.makefile("rb")
        self.client_writer = self.client_sock.makefile("wb")
        self.host_reader = self.host_sock.makefile("rb")
        self.host_writer = self.host_sock.makefile("wb")

        self.handlers: dict[str, Handler] = {
            "fs.read": self.read,
            "test.echo": lambda payload: payload,
            "test.fail": self.fail,
            "test.sleep": self.sleep,
        }
        if handlers:
            self.handlers.update(handlers)

        self._write_lock = threading.Lock()
        self._thread = threading.Thread(target=self._serve, name="fake-host", daemon=True)
        self.client: Client | None = None

    def __enter__(self) -> "FakeHost":
        self._thread.start()
        self.client = Client(
            reader=self.client_reader,
            writer=self.client_writer,
            handshake=True,
            handshake_timeout=2.0,
            call_timeout=2.0,
        )
        return self

    def __exit__(self, *exc: object) -> bool:
        if self.client is not None:
            self.client.close()
        for sock in (self.client_sock, self.host_sock):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self._thread.join(timeout=1.0)
        for stream in (self.client_reader, self.client_writer, self.host_reader, self.host_writer):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        return False

    def _serve(self) -> None:
        try:
            for line in self.host_reader:
                message = json.loads(line)
                kind = message.get("type")
                if kind == "hello":
                    self._send(
                        {
                            "type": "hello",
                            "protocol": 1,
                            "tools": sorted(self.handlers),
                            "limits": {"calls": 200, "concurrency": 8},
                        }
                    )
                elif kind == "call":
                    self._handle(message)
                elif kind == "cancel":
                    pass
        except (OSError, ValueError):
            pass

    def _handle(self, message: dict[str, Any]) -> None:
        call_id = message["id"]
        tool = message["tool"]
        payload = message.get("input") or {}
        handler = self.handlers.get(tool)
        if handler is None:
            self._send(
                {
                    "type": "result",
                    "id": call_id,
                    "ok": False,
                    "error": {"kind": "unavailable", "message": f"unknown tool: {tool}"},
                }
            )
            return

        try:
            output = handler(payload)
        except Exception as error:  # fake host: every failure is a tool failure
            self._send(
                {
                    "type": "result",
                    "id": call_id,
                    "ok": False,
                    "error": {"kind": "tool_failed", "message": str(error)},
                }
            )
            return

        if isinstance(output, dict) and "__error__" in output:
            self._send({"type": "result", "id": call_id, "ok": False, "error": output["__error__"]})
        else:
            self._send({"type": "result", "id": call_id, "ok": True, "output": output})

    def _send(self, message: dict[str, Any]) -> None:
        data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        with self._write_lock:
            self.host_writer.write(data)
            self.host_writer.flush()

    def read(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "file",
            "path": payload.get("path", "?"),
            "text": "hello\n",
            "lines": 1,
            "truncated": False,
        }

    def fail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"__error__": {"kind": "permission_denied", "message": "nope"}}

    def sleep(self, payload: dict[str, Any]) -> dict[str, Any]:
        seconds = float(payload.get("seconds", 0.05))
        time.sleep(seconds)
        return {"slept": seconds}
