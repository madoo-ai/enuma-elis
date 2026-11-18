"""The shared session browser.

The host owns exactly one Chromium per process and attaches it to the session
the human is watching. :func:`page` is a façade over that one browser. It takes
no endpoint, session, or instance argument, and there is no launch, connect, or
close operation: the fork's ``browser`` tool always calls ``Browser.Service``,
whose ``ensure``/``endpoint`` methods resolve to the process browser.

Every action below becomes one ``browser.call`` bridge call. Take a snapshot
before acting; ``@ref`` values expire when the page changes.
"""

from __future__ import annotations

import json
from typing import Any

from . import current_client
from ._errors import AgentError
from ._types import Screenshot, parse_screenshot


def _decoded(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _get_value(what: str, text: str) -> Any:
    data = _decoded(text)
    if not isinstance(data, dict):
        return data
    if what == "styles" and isinstance(data.get("styles"), dict):
        return data["styles"]
    for key in ("text", "html", "value", "title", "url", "count"):
        if key in data:
            return data[key]
    return data


class Page:
    """A stateless façade over the session's one browser page."""

    def _raw(self, action: str, **fields: Any) -> Any:
        payload: dict[str, Any] = {"action": action}
        for key, value in fields.items():
            if value is not None:
                payload[key] = value
        return current_client().call("browser.call", payload)

    def _text(self, action: str, **fields: Any) -> str:
        value = self._raw(action, **fields)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return str(value.get("text", ""))
        return str(value)

    # Navigating.
    def goto(self, url: str) -> str:
        return self._text("navigate", url=url)

    def open(self, url: str) -> str:
        return self.goto(url)

    def back(self) -> str:
        return self._text("back")

    def forward(self) -> str:
        return self._text("forward")

    def reload(self) -> str:
        return self._text("reload")

    def push_state(self, url: str) -> str:
        return self._text("pushstate", url=url)

    def pushstate(self, url: str) -> str:
        return self.push_state(url)

    # Reading the page.
    def snapshot(
        self,
        full: bool = False,
        urls: bool = False,
        compact: bool = False,
        depth: int | None = None,
        selector: str | None = None,
    ) -> str:
        return self._text(
            "snapshot",
            full=full,
            urls=urls,
            compact=compact,
            depth=depth,
            selector=selector,
        )

    def read(self) -> str:
        """Read the page's visible text."""

        return self.get("text", "body")

    def text(self) -> str:
        return self.read()

    def get(self, what: str, target: str | None = None, name: str | None = None) -> Any:
        """Read one value: text, html, value, attr, title, url, count, box, or styles."""

        return _get_value(what, self._text("get", what=what, target=target, name=name))

    def is_(self, what: str, target: str) -> bool:
        """Test visible, enabled, or checked."""

        value = _decoded(self._text("is", what=what, target=target))
        if isinstance(value, dict):
            for key in (what, "value", "result"):
                if key in value:
                    return bool(value[key])
        return bool(value)

    def find(
        self,
        locator: str,
        value: str,
        action: str,
        name: str | None = None,
        exact: bool = False,
    ) -> str:
        return self._text(
            "find",
            locator=locator,
            text=value,
            what=action,
            name=name,
            exact=exact,
        )

    def console(self, clear: bool = False) -> str:
        return self._text("console", clear=clear)

    def errors(self, clear: bool = False) -> str:
        return self._text("errors", clear=clear)

    def network(self) -> str:
        return self._text("network")

    def vitals(self, url: str | None = None) -> str:
        return self._text("vitals", url=url)

    def diff(self) -> str:
        return self._text("diff")

    # Acting on the page.
    def click(self, target: str) -> str:
        return self._text("click", target=target)

    def dblclick(self, target: str) -> str:
        return self._text("dblclick", target=target)

    def hover(self, target: str) -> str:
        return self._text("hover", target=target)

    def focus(self, target: str) -> str:
        return self._text("focus", target=target)

    def check(self, target: str) -> str:
        return self._text("check", target=target)

    def uncheck(self, target: str) -> str:
        return self._text("uncheck", target=target)

    def select(self, target: str, value: str) -> str:
        return self._text("select", target=target, text=value)

    def fill(self, target: str, text: str) -> str:
        return self._text("fill", target=target, text=text)

    def type(self, target: str, text: str) -> str:
        return self._text("type", target=target, text=text)

    def press(self, key: str) -> str:
        return self._text("press", text=key)

    def keyboard_type(self, text: str) -> str:
        return self._text("keyboard", text=text)

    def keyboard(self, text: str) -> str:
        return self.keyboard_type(text)

    def keyboard_insert(self, text: str) -> str:
        return self._text("keyboardinsert", text=text)

    def scroll(
        self,
        direction: str = "down",
        px: int | None = None,
        selector: str | None = None,
    ) -> str:
        return self._text("scroll", text=direction, px=px, selector=selector)

    def scroll_into_view(self, target: str) -> str:
        return self._text("scrollintoview", target=target)

    def drag(self, source: str, destination: str) -> str:
        return self._text("drag", target=source, into=destination)

    def upload(self, target: str, *files: str) -> str:
        if not files:
            raise AgentError("invalid_argument", "upload needs at least one file path")
        return self._text("upload", target=target, text=",".join(files))

    def download(self, target: str, path: str) -> str:
        return self._text("download", target=target, text=path)

    def mouse_move(self, x: int, y: int) -> str:
        return self._text("mouse", what="move", text=f"{x} {y}")

    def mouse_down(self, button: str = "left") -> str:
        return self._text("mouse", what="down", text=button)

    def mouse_up(self, button: str = "left") -> str:
        return self._text("mouse", what="up", text=button)

    def mouse_wheel(self, dy: int, dx: int = 0) -> str:
        return self._text("mouse", what="wheel", text=f"{dy} {dx}")

    # Waiting.
    def wait(self, target: str) -> str:
        return self._text("wait", target=target)

    def wait_ms(self, milliseconds: int) -> str:
        return self._text("waitms", text=str(milliseconds))

    def wait_text(self, text: str) -> str:
        return self._text("waittext", text=text)

    def wait_url(self, url: str) -> str:
        return self._text("waiturl", url=url)

    def wait_load(self, state: str) -> str:
        return self._text("waitload", text=state)

    def wait_function(self, script: str) -> str:
        return self._text("waitfn", script=script)

    def wait_state(self, target: str, state: str) -> str:
        return self._text("waitstate", target=target, text=state)

    def wait_download(self, path: str) -> str:
        return self._text("waitdownload", text=path)

    # Tabs. No close: the human's tab is not ours to remove.
    def tab_new(self, url: str | None = None) -> str:
        return self._text("tabnew", url=url)

    def tab_list(self) -> str:
        return self._text("tablist")

    def tabs(self) -> str:
        return self.tab_list()

    def tab_select(self, target: str) -> str:
        return self._text("tabselect", target=target)

    # Capturing and inspecting.
    def screenshot(
        self,
        path: str | None = None,
        full: bool = False,
        selector: str | None = None,
    ) -> Screenshot:
        value = self._raw("screenshot", text=path, full=full, selector=selector)
        if isinstance(value, str):
            value = {"path": value}
        return parse_screenshot(value)

    def pdf(self, path: str) -> str:
        return self._text("pdf", text=path)

    def highlight(self, target: str) -> str:
        return self._text("highlight", target=target)

    def inspect(self) -> str:
        return self._text("inspect")

    # JavaScript.
    def evaluate(self, script: str) -> str:
        return self._text("evaluate", script=script)

    def eval(self, script: str) -> str:
        return self.evaluate(script)


def page() -> Page:
    """Return the façade for the session browser.

    The host decides which browser that is. This function cannot select or
    start another one.
    """

    return Page()


__all__ = ["Page", "Screenshot", "page"]
