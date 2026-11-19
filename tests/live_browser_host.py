"""Map ``browser.call`` onto the real ``agent-browser`` CLI.

This follows ``me-when-agents/.../tool/browser.ts`` for the actions the live
tests use. It exists so the SDK's parsers meet real output, not hand-written
samples. It runs a private session, never the user's default one.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from typing import Any

SESSION = f"enuma-live-{uuid.uuid4().hex[:8]}"

COMMANDS: dict[str, list[str]] = {
    "navigate": ["open"],
    "back": ["back"],
    "forward": ["forward"],
    "reload": ["reload"],
    "get": ["get"],
    "is": ["is"],
    "console": ["console"],
    "errors": ["errors"],
    "network": ["network", "requests"],
    "diff": ["diff", "snapshot"],
    "click": ["click"],
    "dblclick": ["dblclick"],
    "hover": ["hover"],
    "focus": ["focus"],
    "check": ["check"],
    "uncheck": ["uncheck"],
    "select": ["select"],
    "fill": ["fill"],
    "type": ["type"],
    "press": ["press"],
    "scroll": ["scroll"],
    "scrollintoview": ["scrollintoview"],
    "waitms": ["wait"],
    "tablist": ["tab", "list"],
    "tabnew": ["tab", "new"],
    "tabselect": ["tab", "select"],
    "evaluate": ["eval"],
    "frame": ["frame"],
    "screenshot": ["screenshot"],
}


def _args(payload: dict[str, Any]) -> list[str]:
    action = payload["action"]
    url = payload.get("url")
    target = payload.get("target")
    text = payload.get("text")
    what = payload.get("what")
    if action in ("navigate", "tabnew"):
        return [url] if url else []
    if action == "get":
        if what == "attr":
            return [what, target, payload["name"]]
        return [what, *([target] if target else [])]
    if action == "is":
        return [what, target]
    if action in ("console", "errors"):
        return ["--clear"] if payload.get("clear") else []
    if action in ("click", "dblclick", "hover", "focus", "check", "uncheck", "scrollintoview"):
        return [target]
    if action in ("fill", "type", "select"):
        return [target, text]
    if action == "press":
        return [text]
    if action == "scroll":
        return [text, *([str(payload["px"])] if payload.get("px") is not None else [])]
    if action == "waitms":
        return [text]
    if action == "tabselect":
        return [target]
    if action == "evaluate":
        return [payload["script"]]
    if action == "frame":
        return [target]
    if action == "screenshot":
        return [*([text] if text else [])]
    return []


def browser_call(payload: dict[str, Any], session: str | None = None) -> dict[str, Any]:
    action = payload["action"]
    session = session or SESSION
    if action == "_raw":
        argv = payload["_argv"]
    elif action == "snapshot":
        argv = ["snapshot", *([] if payload.get("full") else ["-i"])]
    elif action == "find":
        argv = [
            "find",
            payload["locator"],
            payload["text"],
            payload["what"],
            *([payload["input"]] if payload.get("input") else []),
        ]
    else:
        argv = [*COMMANDS[action], *_args(payload)]
    done = subprocess.run(
        ["agent-browser", "--session", session, "--json", *argv],
        capture_output=True,
        text=True,
        timeout=60,
    )
    envelope = json.loads(done.stdout or "{}")
    if envelope.get("success") is False:
        raise RuntimeError(str(envelope.get("error")))
    data = envelope.get("data", envelope)
    if action == "snapshot":
        text_out = data["snapshot"] if isinstance(data, dict) else str(data)
    elif isinstance(data, str):
        text_out = data
    else:
        text_out = json.dumps(data, indent=2)
    if action == "screenshot":
        path = data.get("path") if isinstance(data, dict) else None
        return {"action": action, "text": text_out, "path": path or text_out}
    return {"action": action, "text": text_out}


def scratch_call(payload: dict[str, Any]) -> dict[str, Any]:
    """The scratch tool: same CLI, an isolated session, a private profile."""

    session = payload["session"]
    action = payload["action"]
    if action in COMMANDS or action == "snapshot" or action == "find":
        return browser_call(payload, session=session)
    what = payload.get("what")
    text = payload.get("text")
    name = payload.get("name")
    kind = payload.get("locator", "local")
    if action == "viewport":
        argv = ["set", "viewport", *text.split()]
    elif action == "device":
        argv = ["set", "device", text]
    elif action == "geo":
        argv = ["set", "geo", *text.split()]
    elif action == "offline":
        argv = ["set", "offline", "off" if what == "off" else "on"]
    elif action == "media":
        argv = ["set", "media", *([what] if what else []), *(["reduced-motion"] if payload.get("exact") else [])]
    elif action == "headers":
        argv = ["set", "headers", text]
    elif action == "route":
        argv = [
            "network",
            "route",
            payload["url"],
            *(["--abort"] if what == "abort" else []),
            *(["--body", text] if text else []),
            *(["--resource-type", payload["selector"]] if payload.get("selector") else []),
        ]
    elif action == "unroute":
        argv = ["network", "unroute", *([payload["url"]] if payload.get("url") else [])]
    elif action == "cookies":
        argv = [
            "cookies",
            what or "get",
            *([name, text] if what == "set" else []),
            *(["--url", payload["url"]] if what == "set" and payload.get("url") else []),
            *(["--domain", payload["selector"]] if what == "set" and payload.get("selector") else []),
        ]
    elif action == "storage":
        if what == "clear":
            argv = ["storage", kind, "clear"]
        elif what == "set":
            argv = ["storage", kind, "set", name, text]
        else:
            argv = ["storage", kind, "get", *([name] if name else [])]
    elif action == "tabclose":
        argv = ["tab", "close", *([payload["target"]] if payload.get("target") else [])]
    elif action == "close":
        argv = ["close"]
    else:
        raise RuntimeError(f"shim does not know {action}")
    return browser_call({"action": "_raw", "_argv": argv, "session": session}, session=session)


def close_session(session: str = SESSION) -> None:
    subprocess.run(
        ["agent-browser", "--session", session, "close"],
        capture_output=True,
        timeout=30,
    )
