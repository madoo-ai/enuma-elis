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

import fnmatch
import functools
import json
import os
import re
import time
import urllib.parse
import uuid
from typing import Any, Callable

from . import current_client
from ._errors import AgentError
from ._types import (
    ConsoleMessage,
    Diff,
    Link,
    Node,
    PageError,
    PageReport,
    Request,
    Screenshot,
    Tab,
    parse_console,
    parse_diff,
    parse_page_errors,
    parse_requests,
    parse_screenshot,
    parse_snapshot,
    parse_tabs,
)


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


_FUNCTION_EXPR = re.compile(
    r"^\s*(?:"
    r"(?:async\s+)?function\b"
    r"|(?:async\s+)?[A-Za-z_$][\w$]*\s*=>"
    r"|(?:async\s+)?\((?:[^()]|\([^()]*\))*\)\s*=>"
    r")"
)


def _invoke_function(script: str) -> str:
    """Turn a bare zero-argument function expression into an immediate call.

    Playwright accepts functions in ``evaluate``. The browser CLI evaluates a
    function expression as a value and returns ``{}``, so normalise that common
    form before sending it.
    """

    text = script.strip()
    candidate = text[:-1].rstrip() if text.endswith(";") else text
    if candidate and _FUNCTION_EXPR.match(candidate):
        return f"({candidate})()"
    return script


def _node_summary(pool: tuple[Node, ...] | list[Node], role: str | None = None) -> str:
    """A short list of available nodes, useful in not-found errors."""

    usable = [node for node in pool if node.ref] or list(pool)
    without_root = [node for node in usable if node.role != "generic"]
    usable = without_root or usable
    if role is not None:
        usable = sorted(usable, key=lambda node: node.role != role)
    shown = usable[:12]
    names = ", ".join(f"{node.role} {node.name[:80]!r}" for node in shown)
    more = f"; +{len(usable) - len(shown)} more" if len(usable) > len(shown) else ""
    return f"{len(usable)} nodes: {names or 'none'}{more}"


def _recorded(method: Callable[..., Any]) -> Callable[..., Any]:
    """Log a successful action as a line of Python for ``Page.to_script``."""

    @functools.wraps(method)
    def wrapper(self: "Page", *args: Any, **kwargs: Any) -> Any:
        result = method(self, *args, **kwargs)
        if not self._muted:
            note = ""
            if any(isinstance(arg, str) and arg.startswith("@e") for arg in args):
                note = "  # a ref from an earlier snapshot; use find_one(...) for a replayable script"
            self._log(f"page.{method.__name__}({_call_args(args, kwargs)}){note}")
        return result

    return wrapper


def _call_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    parts = [repr(arg) for arg in args] + [f"{key}={value!r}" for key, value in kwargs.items()]
    return ", ".join(parts)


_RETRY_KINDS = {"tool_failed", "not_found"}


class Element:
    """A page element found by role and name, not by a ref that can expire.

    Each action tries the current ref. If the tool fails, the handle takes a
    fresh snapshot, looks for the same role and name (and the same position
    among matches), and retries once. The snapshot itself is what makes a ref
    valid again, so the retry happens even when the number is unchanged. If the
    element is gone, or the retry fails, the error is raised as it is.
    """

    def __init__(self, page: "Page", node: Node, nth: int, full: bool) -> None:
        self.page = page
        self.role = node.role
        self.name = node.name
        self.value = node.value
        self.nth = nth
        self.full = full
        self.ref = node.ref

    _FIELDS = ("role", "name", "value", "ref", "nth", "full")

    def __repr__(self) -> str:
        return f"Element(role={self.role!r}, name={self.name!r}, ref={self.ref!r})"

    def __getitem__(self, key: str) -> Any:
        if key in self._FIELDS:
            return getattr(self, key)
        raise KeyError(f"{key!r}; Element fields: {', '.join(self._FIELDS)}")

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self) -> list[str]:
        return list(self._FIELDS)

    def items(self) -> list[tuple[str, Any]]:
        return [(key, getattr(self, key)) for key in self._FIELDS]

    def values(self) -> list[Any]:
        return [getattr(self, key) for key in self._FIELDS]

    @property
    def target(self) -> str:
        return f"@{self.ref}"

    def _resolve(self) -> str | None:
        matches = self.page.find_all(role=self.role, name=self.name, full=self.full)
        return matches[self.nth].ref if len(matches) > self.nth else None

    def _expression(self, action: str, *args: Any) -> str:
        spec = _call_args((), {"role": self.role, "name": self.name} | ({"nth": self.nth} if self.nth else {}))
        return f"page.find_one({spec}).{action}({_call_args(args, {})})"

    def _act(self, action: str, method: Callable[..., Any], *args: Any, record: bool = True) -> Any:
        page = self.page
        page._muted += 1
        try:
            try:
                result = method(self.target, *args)
            except AgentError as error:
                if error.kind not in _RETRY_KINDS:
                    raise
                fresh = self._resolve()
                if fresh is None:
                    raise
                self.ref = fresh
                result = method(self.target, *args)
        finally:
            page._muted -= 1
        if record and not page._muted:
            page._log(self._expression(action, *args))
        return result

    def click(self) -> str:
        return self._act("click", self.page.click)

    def dblclick(self) -> str:
        return self._act("dblclick", self.page.dblclick)

    def hover(self) -> str:
        return self._act("hover", self.page.hover)

    def focus(self) -> str:
        return self._act("focus", self.page.focus)

    def check(self) -> str:
        return self._act("check", self.page.check)

    def uncheck(self) -> str:
        return self._act("uncheck", self.page.uncheck)

    def fill(self, text: str) -> str:
        return self._act("fill", self.page.fill, text)

    def type(self, text: str) -> str:
        return self._act("type", self.page.type, text)

    def select(self, value: str) -> str:
        return self._act("select", self.page.select, value)

    def press(self, key: str) -> str:
        """Focus this element and press a key, for example ``press("Enter")``."""

        def send(target: str) -> str:
            self.page._text("focus", target=target)
            return self.page.press(key)

        return self._act("press", send)

    def scroll_into_view(self) -> str:
        return self._act("scroll_into_view", self.page.scroll_into_view)

    def text(self) -> str:
        return str(self._act("text", lambda target: self.page.get("text", target), record=False))

    def input_value(self) -> str:
        return str(self._act("input_value", lambda target: self.page.get("value", target), record=False))

    def box(self) -> dict[str, float]:
        return self._act("box", lambda target: self.page.get("box", target), record=False)

    def is_visible(self) -> bool:
        return bool(self._act("is_visible", lambda target: self.page.is_("visible", target), record=False))


# Spellings models reach for, mapped to the state the browser reports.
_INVERSE = {"disabled": "enabled", "hidden": "visible", "invisible": "visible", "unchecked": "checked"}


_STRING_FIELDS = {"text", "url", "target", "selector", "name", "what", "script", "locator", "into", "input"}


class Page:
    """A façade over the session's one browser page.

    The page itself is not held here; every call goes to the shared browser. An
    instance only remembers the actions it ran, for :meth:`to_script`.
    """

    def __init__(self, session: str | None = None) -> None:
        self.history: list[str] = []
        self.session = session
        self._muted = 0
        self._closed = False

    @property
    def tool(self) -> str:
        return "browser.scratch" if self.session else "browser.call"

    def _log(self, line: str) -> None:
        self.history.append(line)

    def _raw(self, action: str, **fields: Any) -> Any:
        if self._closed:
            raise AgentError("unavailable", "this scratch browser is closed; call browser.scratch() again")
        payload: dict[str, Any] = {"action": action}
        if self.session:
            payload["session"] = self.session
        for key, value in fields.items():
            if value is None:
                continue
            # The tool takes strings here; a number is a clear intent.
            if key in _STRING_FIELDS and isinstance(value, (int, float)) and not isinstance(value, bool):
                value = str(value)
            payload[key] = value
        return current_client().call(self.tool, payload)

    def _text(self, action: str, **fields: Any) -> str:
        value = self._raw(action, **fields)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return str(value.get("text", ""))
        return str(value)

    # Navigating.
    @_recorded
    def goto(self, url: str) -> str:
        return self._text("navigate", url=url)

    def open(self, url: str) -> str:
        return self.goto(url)

    @_recorded
    def back(self) -> str:
        return self._text("back")

    @_recorded
    def forward(self) -> str:
        return self._text("forward")

    @_recorded
    def reload(self) -> str:
        return self._text("reload")

    @_recorded
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

    def title(self) -> str:
        """The page title."""

        return str(self.get("title"))

    def url(self) -> str:
        """The current URL."""

        return str(self.get("url"))

    def get(self, what: str, target: str | None = None, name: str | None = None) -> Any:
        """Read one value: text, html, value, attr, title, url, count, box, or styles.

        ``title`` and ``url`` take no target; ``text`` defaults to the whole page.
        """

        if what in ("title", "url"):
            target = None
        elif what == "text" and target is None:
            target = "body"
        return _get_value(what, self._text("get", what=what, target=target, name=name))

    def is_(self, what: str, target: str) -> bool:
        """Test visible, enabled, or checked.

        The inverse spellings ``hidden``, ``disabled``, and ``unchecked`` are
        accepted too: they query the positive state and negate it.
        """

        positive = _INVERSE.get(what, what)
        value = _decoded(self._text("is", what=positive, target=target))
        if isinstance(value, dict):
            for key in (positive, "value", "result", what):
                if key in value:
                    result = bool(value[key])
                    break
            else:
                result = bool(value)
        else:
            result = bool(value)
        return not result if what in _INVERSE else result

    @_recorded
    def find(
        self,
        locator: str,
        value: str,
        action: str,
        name: str | None = None,
        exact: bool = False,
        input: str | None = None,
    ) -> str:
        """Locate by role, text, label, ... and act at once.

        ``input`` is the text for a ``fill`` or ``type`` action:
        ``find("label", "Email", "fill", input="a@b.c")``.
        """

        return self._text(
            "find",
            locator=locator,
            text=value,
            what=action,
            name=name,
            exact=exact,
            input=input,
        )

    def console(self, clear: bool = False) -> tuple[ConsoleMessage, ...]:
        """Console messages: each has ``type`` (log, warning, error) and ``text``."""

        return parse_console(self._text("console", clear=clear))

    def errors(self, clear: bool = False) -> tuple[PageError, ...]:
        """Uncaught JavaScript errors: ``text``, ``line``, ``column``, ``url``."""

        return parse_page_errors(self._text("errors", clear=clear))

    def network(self) -> tuple[Request, ...]:
        """Requests the page made: ``url``, ``method``, ``status``, ``type``, ``ok``."""

        return parse_requests(self._text("network"))

    def vitals(self, url: str | None = None) -> str:
        return self._text("vitals", url=url)

    def diff(self) -> Diff:
        """What changed in the snapshot since the last one."""

        return parse_diff(self._text("diff"))

    # Acting on the page.
    @_recorded
    def click(self, target: str) -> str:
        return self._text("click", target=target)

    @_recorded
    def dblclick(self, target: str) -> str:
        return self._text("dblclick", target=target)

    @_recorded
    def hover(self, target: str) -> str:
        return self._text("hover", target=target)

    @_recorded
    def focus(self, target: str) -> str:
        return self._text("focus", target=target)

    @_recorded
    def check(self, target: str) -> str:
        return self._text("check", target=target)

    @_recorded
    def uncheck(self, target: str) -> str:
        return self._text("uncheck", target=target)

    @_recorded
    def select(self, target: str, value: str) -> str:
        return self._text("select", target=target, text=value)

    @_recorded
    def fill(self, target: str, text: str) -> str:
        return self._text("fill", target=target, text=text)

    @_recorded
    def type(self, target: str, text: str) -> str:
        return self._text("type", target=target, text=text)

    @_recorded
    def press(self, key: str) -> str:
        return self._text("press", text=key)

    @_recorded
    def keyboard_type(self, text: str) -> str:
        return self._text("keyboard", text=text)

    def keyboard(self, text: str) -> str:
        return self.keyboard_type(text)

    @_recorded
    def keyboard_insert(self, text: str) -> str:
        return self._text("keyboardinsert", text=text)

    @_recorded
    def scroll(
        self,
        direction: str = "down",
        px: int | None = None,
        selector: str | None = None,
    ) -> str:
        if direction not in ("up", "down", "left", "right"):
            raise AgentError(
                "invalid_argument",
                f"scroll direction must be 'up', 'down', 'left', or 'right', not {direction!r}; "
                "for a distance use scroll('down', 400)",
            )
        return self._text("scroll", text=direction, px=px, selector=selector)

    @_recorded
    def scroll_into_view(self, target: str) -> str:
        return self._text("scrollintoview", target=target)

    @_recorded
    def drag(self, source: str, destination: str) -> str:
        return self._text("drag", target=source, into=destination)

    @_recorded
    def upload(self, target: str, *files: str) -> str:
        if not files:
            raise AgentError("invalid_argument", "upload needs at least one file path")
        return self._text("upload", target=target, text=",".join(files))

    @_recorded
    def download(self, target: str, path: str) -> str:
        return self._text("download", target=target, text=path)

    @_recorded
    def mouse_move(self, x: int, y: int) -> str:
        return self._text("mouse", what="move", text=f"{x} {y}")

    @_recorded
    def mouse_down(self, button: str = "left") -> str:
        return self._text("mouse", what="down", text=button)

    @_recorded
    def mouse_up(self, button: str = "left") -> str:
        return self._text("mouse", what="up", text=button)

    @_recorded
    def mouse_wheel(self, dy: int, dx: int = 0) -> str:
        return self._text("mouse", what="wheel", text=f"{dy} {dx}")

    # Waiting.
    @_recorded
    def wait(self, target: str) -> str:
        return self._text("wait", target=target)

    @_recorded
    def wait_ms(self, milliseconds: int) -> str:
        return self._text("waitms", text=str(milliseconds))

    @_recorded
    def wait_text(self, text: str, timeout: float = 30.0) -> str:
        """Wait until the page's visible text contains ``text``.

        The native wait handles the default timeout in one browser call.
        Custom timeouts keep the polling fallback.
        """

        last = ""

        def found() -> bool:
            nonlocal last
            last = str(self.get("text", "body"))
            return text in last

        def timeout_error(error: AgentError) -> AgentError:
            try:
                current = self.url()
            except AgentError:
                current = "?"
            return AgentError(
                "timeout",
                f"{error.message}; current url={current!r}; text tail={last[-240:]!r}",
            )

        try:
            if timeout == 30.0:
                return self._text("waittext", text=text)
            self.until(
                found,
                timeout=timeout,
                message=f"text {text!r} did not appear within {timeout:g}s",
            )
        except AgentError as error:
            if error.kind != "timeout":
                raise
            if not last:
                try:
                    last = str(self.get("text", "body"))
                except AgentError:
                    pass
            raise timeout_error(error) from error
        return text

    @_recorded
    def wait_gone(self, text: str, timeout: float = 30.0) -> str:
        """Wait until the page's visible text no longer contains ``text``."""

        self.until(
            lambda: text not in str(self.get("text", "body")),
            timeout=timeout,
            message=f"text {text!r} was still there after {timeout:g}s",
        )
        return text

    @_recorded
    def wait_count(self, selector: str, count: int, timeout: float = 30.0) -> int:
        """Wait until ``selector`` matches exactly ``count`` elements."""

        self.until(
            lambda: self.get("count", selector) == count,
            timeout=timeout,
            message=f"{selector!r} did not reach {count} matches within {timeout:g}s",
        )
        return count

    @_recorded
    def wait_for(
        self,
        role: str | None = None,
        name: str | None = None,
        contains: str | None = None,
        timeout: float = 30.0,
        full: bool = True,
    ) -> "Element | Node":
        """Wait for a node by role and name.

        Interactive matches have a ref and return ``Element``. Structural
        matches such as ``dialog`` return ``Node``; use ``wait_for(role=...)``
        to wait for either.
        """

        last: list[Node] = []

        def found() -> "Element | Node | None":
            last[:] = list(self.nodes(full=full))
            matches = self._matching(last, role, name, contains, require_ref=False)
            if not matches:
                return None
            node = matches[0]
            return self._element(matches, 0, full) if node.ref else node

        try:
            return self.until(
                found,
                timeout=timeout,
                message=f"no element role={role!r} name={name!r} contains={contains!r} within {timeout:g}s",
            )
        except AgentError as error:
            if error.kind != "timeout":
                raise
            raise AgentError(
                "timeout",
                f"{error.message}; page has: {_node_summary(last, role)}",
            ) from error

    def until(
        self,
        predicate: Callable[[], Any],
        timeout: float = 30.0,
        interval: float = 0.25,
        message: str | None = None,
    ) -> Any:
        """Call ``predicate`` until it returns something truthy, and return that.

        A tool failure inside the predicate counts as "not yet" and is kept for
        the final error. A refused or unavailable call is raised at once.
        """

        deadline = time.monotonic() + timeout
        last: AgentError | None = None
        delay = interval
        cap = max(interval, 0.5)
        while True:
            try:
                value = predicate()
                if value:
                    return value
            except AgentError as error:
                if error.kind in {"unavailable", "permission_denied", "invalid_input", "invalid_argument"}:
                    raise
                last = error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason = message or f"condition not met within {timeout:g}s"
                if last is not None:
                    reason += f"; last error: {last}"
                raise AgentError("timeout", reason)
            time.sleep(min(delay, remaining))
            delay = min(delay * 1.5, cap)

    @_recorded
    def wait_url(self, url: str, timeout: float = 30.0) -> str:
        """Wait until the current URL matches a glob, including queries."""

        last = ""

        def matched() -> str | None:
            nonlocal last
            last = self.url()
            return last if fnmatch.fnmatch(last, url) else None

        try:
            return self.until(
                matched,
                timeout=timeout,
                message=f"URL did not match {url!r} within {timeout:g}s",
            )
        except AgentError as error:
            if error.kind != "timeout":
                raise
            raise AgentError(
                "timeout",
                f"URL {last!r} did not match {url!r} within {timeout:g}s",
            ) from error

    def wait_for_url(self, url: str, timeout: float = 30.0) -> str:
        return self.wait_url(url, timeout)

    @_recorded
    def wait_load(self, state: str = "load", timeout: float = 30.0) -> str:
        """Wait for a document load state.

        ``load`` and ``domcontentloaded`` use ``document.readyState`` because
        agent-browser's ``wait --load`` reports success after a 25-second stall
        on an already-loaded page. ``networkidle`` keeps the native wait.
        """

        if state == "networkidle":
            return self._text("waitload", text=state)
        if state not in ("load", "domcontentloaded"):
            raise AgentError(
                "invalid_argument",
                f"load state must be 'load', 'domcontentloaded', or 'networkidle', not {state!r}",
            )
        last = ""

        def loaded() -> str | None:
            nonlocal last
            ready = str(self.evaluate("document.readyState"))
            last = ready
            if state == "load":
                return ready if ready == "complete" else None
            return ready if ready in ("interactive", "complete") else None

        try:
            self.until(
                loaded,
                timeout=timeout,
                interval=0.1,
                message=f"document did not reach {state!r} within {timeout:g}s",
            )
        except AgentError as error:
            if error.kind != "timeout":
                raise
            raise AgentError(
                "timeout",
                f"document readyState={last!r} did not reach {state!r} within {timeout:g}s",
            ) from error
        return state

    def wait_for_load(self, state: str = "load", timeout: float = 30.0) -> str:
        return self.wait_load(state, timeout)

    @_recorded
    def wait_function(self, script: str) -> str:
        return self._text("waitfn", script=script)

    @_recorded
    def wait_state(self, target: str, state: str) -> str:
        return self._text("waitstate", target=target, text=state)

    @_recorded
    def wait_download(self, path: str) -> str:
        return self._text("waitdownload", text=path)

    # Tabs. No close: the human's tab is not ours to remove.
    @_recorded
    def tab_new(self, url: str | None = None) -> str:
        return self._text("tabnew", url=url)

    def tab_list(self) -> tuple[Tab, ...]:
        """Open tabs: ``id``, ``url``, ``title``, ``active``."""

        return parse_tabs(self._text("tablist"))

    def tabs(self) -> tuple[Tab, ...]:
        return self.tab_list()

    @_recorded
    def tab_select(self, target: str) -> str:
        return self._text("tabselect", target=target)

    # Capturing and inspecting.
    @_recorded
    def screenshot(
        self,
        path: str | None = None,
        full: bool = False,
        selector: str | None = None,
        save: str | None = None,
    ) -> Screenshot:
        """Capture the page or one element.

        ``save="out.png"`` also writes the image into the program's workspace,
        which a sandboxed program cannot do with the host's ``path``.
        """

        value = self._raw("screenshot", text=path, full=full, selector=selector)
        if isinstance(value, str):
            value = {"path": value}
        shot = parse_screenshot(value)
        if save:
            shot.save(save)
        return shot

    @_recorded
    def pdf(self, path: str) -> str:
        return self._text("pdf", text=path)

    @_recorded
    def highlight(self, target: str) -> str:
        return self._text("highlight", target=target)

    def inspect(self) -> str:
        return self._text("inspect")

    # JavaScript.
    def evaluate(self, script: str) -> Any:
        """Run JavaScript in the page and return its value (decoded JSON).

        Accepts an expression or a zero-argument function; a bare function is
        invoked before evaluation.
        """

        data = _decoded(self._text("evaluate", script=_invoke_function(script)))
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data

    def eval(self, script: str) -> Any:
        return self.evaluate(script)

    # Structure: find elements by role and name instead of reading refs.
    def nodes(self, full: bool = False, **snapshot: Any) -> tuple[Node, ...]:
        """The snapshot as nodes with ``role``, ``name``, ``ref``, ``value``.

        By default only interactive nodes appear; ``full=True`` adds the rest
        (text, structure).
        """

        return parse_snapshot(self.snapshot(full=full, **snapshot))

    def _matching(
        self,
        pool: tuple[Node, ...] | list[Node],
        role: str | None,
        name: str | None,
        contains: str | None,
        require_ref: bool = True,
    ) -> list[Node]:
        out = []
        for node in pool:
            if require_ref and not node.ref:
                continue
            if role is not None and node.role != role:
                continue
            if name is not None and node.name != name:
                continue
            if contains is not None:
                haystack = f"{node.name} {node.value or ''}".lower()
                if contains.lower() not in haystack:
                    continue
            out.append(node)
        return out

    def find_all(
        self,
        role: str | None = None,
        name: str | None = None,
        contains: str | None = None,
        full: bool = False,
    ) -> list[Element]:
        """Element handles matching ``role``, exact ``name``, or ``contains``.

        Every handle can act, just like one from :meth:`find_one`. Use
        :meth:`nodes` when the raw accessibility records are wanted.
        """

        matches = self._matching(self.nodes(full=full), role, name, contains)
        return [self._element(matches, index, full) for index in range(len(matches))]

    def _element(self, matches: list[Node], nth: int, full: bool) -> Element:
        return Element(self, matches[nth], nth, full)

    def find_one(
        self,
        role: str | None = None,
        name: str | None = None,
        contains: str | None = None,
        nth: int = 0,
        full: bool = False,
    ) -> Element:
        """Return a handle to one element, or raise ``not_found`` listing what exists."""

        pool = self.nodes(full=full)
        matches = self._matching(pool, role, name, contains)
        if len(matches) <= nth:
            hint = "; name is exact; use contains= for a substring" if name is not None else ""
            raise AgentError(
                "not_found",
                f"no element role={role!r} name={name!r} contains={contains!r} (match {nth}); "
                f"page has: {_node_summary(pool, role)}{hint}",
            )
        return self._element(matches, nth, full)

    # Extraction: fixed scripts, so a program does not write its own JavaScript.
    def links(self) -> list[Link]:
        """Every link as ``Link(text, href, name)``."""

        rows = self.evaluate(
            "[...document.querySelectorAll('a[href]')]"
            ".map(a => ({text: a.innerText.trim(), href: a.href}))"
        )
        return [
            Link(text=str(row.get("text", "")), href=str(row.get("href", "")))
            for row in rows
            if isinstance(row, dict)
        ]

    def headings(self) -> list[dict[str, Any]]:
        """Every heading as ``{"level", "text"}``."""

        return self.evaluate(
            "[...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]"
            ".map(h => ({level: Number(h.tagName[1]), text: h.innerText.trim()}))"
        )

    def forms(self) -> list[dict[str, Any]]:
        """Every form with its action, method, and fields (name, type, label, value)."""

        return self.evaluate(
            "[...document.forms].map(f => ({"
            "action: f.action, method: f.method,"
            "fields: [...f.elements].filter(e => e.name || e.id).map(e => ({"
            "name: e.name || e.id, type: e.type || e.tagName.toLowerCase(),"
            "label: (e.labels && e.labels[0] ? e.labels[0].innerText.trim() : e.getAttribute('aria-label')),"
            "value: e.value}))}))"
        )

    def table(self, selector: str = "table") -> list[dict[str, str]]:
        """A table as a list of rows keyed by header text.

        Headers come from ``th`` cells of the first row. A table without them
        gives keys ``"0"``, ``"1"``, ...
        """

        script = (
            "(() => { const t = document.querySelector(%s); if (!t) return null;"
            "const rows = [...t.rows].map(r => [...r.cells].map(c => c.innerText.trim()));"
            "const head = t.rows[0] && [...t.rows[0].cells].every(c => c.tagName === 'TH');"
            "return {head, rows}; })()" % json.dumps(selector)
        )
        data = self.evaluate(script)
        if not isinstance(data, dict):
            raise AgentError("not_found", f"no table matches {selector!r}")
        rows = data["rows"]
        if data.get("head") and rows:
            headers, rows = rows[0], rows[1:]
        else:
            headers = [str(index) for index in range(len(rows[0]) if rows else 0)]
        return [dict(zip(headers, row)) for row in rows]

    def extract(self, fields: dict[str, str]) -> dict[str, Any]:
        """Read several values at once.

        Each value is a CSS selector: ``"h1"`` is the first match's text,
        ``"a.more@href"`` is an attribute, and ``"li.item[]"`` is every match's
        text as a list. A selector that matches nothing gives ``None`` (or ``[]``).
        """

        script = (
            "((spec) => Object.fromEntries(Object.entries(spec).map(([key, sel]) => {"
            "const all = sel.endsWith('[]'); if (all) sel = sel.slice(0, -2);"
            "const at = sel.lastIndexOf('@'); "
            "const attr = at > 0 && /^[A-Za-z_][\\w-]*$/.test(sel.slice(at + 1)) ? sel.slice(at + 1) : null;"
            "if (attr) sel = sel.slice(0, at);"
            "const read = e => attr ? e.getAttribute(attr) : e.innerText.trim();"
            "return [key, all ? [...document.querySelectorAll(sel)].map(read)"
            " : (e => e ? read(e) : null)(document.querySelector(sel))];"
            "})))(%s)" % json.dumps(fields)
        )
        return self.evaluate(script)

    # Reports.
    def audit(self, url: str | None = None) -> PageReport:
        """Load ``url`` (optional) and report console errors, page errors, and failed requests.

        With a ``url`` the console and error logs are cleared first, so the
        report covers only this load. Network history cannot be cleared, so it
        can include earlier requests.
        """

        if url:
            self.console(clear=True)
            self.errors(clear=True)
            self.goto(url)
        console = self.console()
        return PageReport(
            url=self.url(),
            title=self.title(),
            console_errors=tuple(m for m in console if m.type == "error"),
            console_warnings=tuple(m for m in console if m.type in ("warning", "warn")),
            page_errors=self.errors(),
            failed_requests=tuple(
                r for r in self.network() if not r.ok and not r.url.endswith("/favicon.ico")
            ),
        )

    def goto_file(self, path: str) -> str:
        """Open a workspace file as a ``file://`` URL."""

        return self.goto("file://" + urllib.parse.quote(os.path.abspath(path)))

    # Frames. There is no dialog method: the browser auto-dismisses alerts.
    @_recorded
    def frame(self, selector: str) -> str:
        """Send later actions into an iframe. Return with ``main_frame()``."""

        return self._text("frame", target=selector)

    @_recorded
    def main_frame(self) -> str:
        return self._text("frame", target="main")

    # Replay.
    def to_script(self) -> str:
        """The actions this page object ran, as a program that replays them."""

        body = [f"    {line}" for line in self.history] or ["    pass"]
        page_expr = "browser.scratch()" if self.session else "browser.page()"
        ending = (
            [
                '    result = {"title": page.title(), "url": page.url()}',
                "    page.close()",
                "    return result",
            ]
            if self.session
            else ['    return {"title": page.title(), "url": page.url()}']
        )
        return "\n".join(
            [
                "from agent import browser",
                "",
                "",
                "def Run(ctx, a):",
                f"    page = {page_expr}",
                *body,
                *ending,
                "",
            ]
        )




def page() -> Page:
    """Return the façade for the session browser.

    The host decides which browser that is. This function cannot select or
    start another one.
    """

    return Page()


__all__ = ["Element", "Link", "Page", "ScratchPage", "Screenshot", "page", "scratch"]


def __dir__() -> list[str]:
    return sorted(__all__)


def _storage_kind(kind: str) -> None:
    if kind not in ("local", "session"):
        raise AgentError(
            "invalid_argument",
            f"storage kind must be 'local' or 'session', not {kind!r}",
        )


class ScratchPage(Page):
    """A headless Chromium the program owns, with a fresh empty profile.

    Everything :class:`Page` does works here. The methods below are the ones the
    shared page cannot allow, because here nothing belongs to the human.
    """

    def __init__(self, session: str) -> None:
        super().__init__(session=session)

    @_recorded
    def viewport(self, width: int, height: int, scale: float | None = None) -> str:
        """Set the viewport size in CSS pixels, with an optional device scale."""

        text = f"{int(width)} {int(height)}" + (f" {scale:g}" if scale else "")
        return self._text("viewport", text=text)

    @_recorded
    def device(self, name: str) -> str:
        """Emulate a device by name, for example ``"iPhone 12"``."""

        return self._text("device", text=name)

    @_recorded
    def geo(self, latitude: float, longitude: float) -> str:
        """Set the geolocation."""

        return self._text("geo", text=f"{latitude:g} {longitude:g}")

    @_recorded
    def offline(self, on: bool = True) -> str:
        """Turn offline mode on (or off with ``on=False``)."""

        return self._text("offline", what="on" if on else "off")

    @_recorded
    def media(self, scheme: str | None = None, reduced_motion: bool = False) -> str:
        """Emulate ``dark`` or ``light`` color scheme and reduced motion."""

        return self._text("media", what=scheme, exact=reduced_motion)

    @_recorded
    def headers(self, headers: dict[str, str] | str) -> str:
        """Send extra HTTP headers, as a dict or a JSON object string."""

        text = headers if isinstance(headers, str) else json.dumps(headers)
        return self._text("headers", text=text)

    @_recorded
    def route(self, url: str, resource_type: str | None = None) -> str:
        """Abort requests matching ``url``. Use a full URL for an exact match.

        Only blocking is exposed: agent-browser's response mocking did not
        intercept requests in 0.27, so a mock would silently not mock.
        """

        return self._text("route", url=url, what="abort", selector=resource_type)

    @_recorded
    def unroute(self, url: str | None = None) -> str:
        """Remove a route, or every route when ``url`` is omitted."""

        return self._text("unroute", url=url)

    def cookies(self) -> Any:
        """All cookies in the private profile, decoded from the tool's JSON."""

        data = _decoded(self._text("cookies", what="get"))
        return data.get("cookies", []) if isinstance(data, dict) else data

    @_recorded
    def set_cookie(
        self,
        name: str,
        value: str,
        url: str | None = None,
        domain: str | None = None,
    ) -> str:
        """Set a cookie. ``url`` lets you set one before the first page load."""

        return self._text("cookies", what="set", name=name, text=value, url=url, selector=domain)

    @_recorded
    def clear_cookies(self) -> str:
        return self._text("cookies", what="clear")

    def storage(self, kind: str = "local", key: str | None = None) -> Any:
        """Read web storage: everything, or one key. ``kind`` is local or session."""

        _storage_kind(kind)
        data = _decoded(self._text("storage", what="get", locator=kind, name=key))
        if isinstance(data, dict):
            if "storage" in data:
                return data["storage"]
            if key is not None and "value" in data:
                return data["value"]
        return data

    @_recorded
    def set_storage(self, key: str, value: str, kind: str = "local") -> str:
        _storage_kind(kind)
        return self._text("storage", what="set", locator=kind, name=key, text=value)

    @_recorded
    def clear_storage(self, kind: str = "local") -> str:
        _storage_kind(kind)
        return self._text("storage", what="clear", locator=kind)

    @_recorded
    def tab_close(self, target: str | None = None) -> str:
        """Close one tab by id or index. This is only possible on a scratch browser."""

        return self._text("tabclose", target=target)

    def close(self) -> str:
        """Close this browser and delete its profile. The handle stops working."""

        if self._closed:
            return "already closed"
        result = self._text("close")
        self._closed = True
        return result


# One scratch browser per program. The host refuses any other session name.
_SESSION = f"enuma-scratch-{uuid.uuid4().hex[:8]}"


def scratch() -> ScratchPage:
    """Return a headless browser the program owns.

    Repeated calls in one program return handles to the same browser, so use
    :meth:`ScratchPage.tab_new` for a second page. Close it with ``close()``
    when you are done; the profile is temporary and deleted then.
    """

    return ScratchPage(_SESSION)
