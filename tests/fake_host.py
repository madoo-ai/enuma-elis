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
            "fs.glob": self.glob,
            "fs.grep": self.grep,
            "mutate.edit": self.edit,
            "mutate.write": self.write,
            "mutate.patch": self.patch,
            "shell.run": self.shell,
            "web.fetch": self.fetch,
            "web.search": self.search,
            "state.skills.load": self.skill,
            "state.todos.write": self.todos,
            "agents.tasks.run": self.task,
            "agents.tasks.start": self.task_start,
            "browser.call": self.browser,
            "test.echo": lambda payload: payload,
            "test.fail": self.fail,
            "test.sleep": self.sleep,
        }
        if handlers:
            self.handlers.update(handlers)

        self.calls: list[tuple[str, dict[str, Any]]] = []
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
                    # A real host runs independent calls concurrently; a single
                    # reader thread would serialize sleeps and hide overlap.
                    threading.Thread(
                        target=self._handle,
                        args=(message,),
                        name="fake-host-call",
                        daemon=True,
                    ).start()
                elif kind == "cancel":
                    pass
        except (OSError, ValueError):
            pass

    def _handle(self, message: dict[str, Any]) -> None:
        call_id = message["id"]
        tool = message["tool"]
        payload = message.get("input") or {}
        self.calls.append((tool, payload))
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
        try:
            with self._write_lock:
                self.host_writer.write(data)
                self.host_writer.flush()
        except (OSError, ValueError):
            # A late concurrent call can finish after the test closed the host.
            pass

    def read(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = str(payload.get("path", "?"))
        if path.endswith(".png"):
            return {
                "kind": "attachment",
                "path": path,
                "mime": "image/png",
                "data": "aGVsbG8=",
                "truncated": False,
            }
        return {
            "kind": "file",
            "path": path,
            "text": "hello\n",
            "lines": 1,
            "truncated": False,
        }

    def glob(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "entries": [{"path": "src/a.py", "type": "file"}],
            "truncated": False,
        }

    def grep(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "matches": [{"path": "src/a.py", "line": 3, "text": "TODO"}],
            "truncated": False,
        }

    def edit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "file": payload.get("path", "?"),
            "replacements": 1,
            "additions": 1,
            "deletions": 1,
            "patch": "--- a\n+++ b",
        }

    def write(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "file": payload.get("path", "?"),
            "bytes": len(str(payload.get("content", ""))),
            "created": True,
        }

    def patch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"files": ["src/a.py"], "diff": "--- a\n+++ b"}

    def shell(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("command") == "false":
            return {
                "exit": 1,
                "stdout": "",
                "stderr": "failed\n",
                "output": "failed\n",
                "truncated": False,
                "timed_out": False,
            }
        return {
            "exit": 0,
            "stdout": "ok\n",
            "stderr": "",
            "output": "ok\n",
            "truncated": False,
            "timed_out": False,
        }

    def fetch(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get("url", ""))
        if url.endswith(".png"):
            return {
                "url": url,
                "text": "Image fetched successfully",
                "title": "",
                "truncated": False,
                "kind": "attachment",
                "mime": "image/png",
                "data": "aGVsbG8=",
            }
        return {
            "url": url,
            "text": "page",
            "title": "title",
            "truncated": False,
        }

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"query": payload.get("query", ""), "text": "results", "provider": "exa"}

    def skill(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": payload.get("name", ""),
            "directory": "/skills/example",
            "content": "# Skill\nDo the thing.",
        }

    def todos(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"todos": payload.get("todos", [])}

    def task(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": "ses_child_demo",
            "output": "child finished",
            "transcript_path": "/home/ubuntu/workspace/.manus/tasks/ses_child_demo.jsonl",
            "background": False,
            "model": "litellm/prometheus",
        }

    def task_start(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": "ses_child_demo",
            "job_id": "ses_child_demo",
            "description": payload.get("description", "python task"),
            "status": "running",
            "background": True,
            "model": "litellm/prometheus",
        }

    def browser(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", ""))
        if action == "screenshot":
            return {
                "action": action,
                "text": "/tmp/shot.png",
                "path": "/tmp/shot.png",
                "mime": "image/png",
                "data": "aGVsbG8=",
            }
        if action == "get":
            what = str(payload.get("what", ""))
            if what == "title":
                return {"action": action, "text": json.dumps({"title": "Example Domain"})}
            if what == "text":
                return {"action": action, "text": json.dumps({"text": "Example Domain. Saved."})}
            if what == "attr":
                return {"action": action, "text": json.dumps({"value": "go"})}
            if what == "styles":
                return {"action": action, "text": json.dumps({"styles": {"display": "block"}})}
        if action == "is":
            return {
                "action": action,
                "text": json.dumps({str(payload.get("what", "visible")): True}),
            }
        return {"action": action, "text": f"{action} ok"}

    def fail(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"__error__": {"kind": "permission_denied", "message": "nope"}}

    def sleep(self, payload: dict[str, Any]) -> dict[str, Any]:
        seconds = float(payload.get("seconds", 0.05))
        time.sleep(seconds)
        return {"slept": seconds}
