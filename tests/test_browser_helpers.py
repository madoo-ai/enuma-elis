"""Browser helpers against scripted replies (no real browser)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from typing import Any

from agent import browser
from agent._errors import AgentError
from agent._types import (
    Screenshot,
    parse_console,
    parse_diff,
    parse_page_errors,
    parse_requests,
    parse_snapshot,
    parse_tabs,
)
from fake_host import FakeHost

TREE = '- heading "Hi" [level=1, ref=e1]\n- button "Save" [ref=e2]\n- button "Save" [ref=e3]\n- textbox "Email" [ref=e4]: a@b.c'


class ScriptedBrowser:
    """A ``browser.call`` handler with queued replies per action."""

    def __init__(self, **replies: Any) -> None:
        self.replies = {key: list(value) if isinstance(value, list) else [value] for key, value in replies.items()}
        self.calls: list[dict[str, Any]] = []

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(payload)
        queue = self.replies.get(payload["action"], [])
        reply = queue.pop(0) if len(queue) > 1 else (queue[0] if queue else f"{payload['action']} ok")
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, dict) and "__error__" in reply:
            return reply
        return {"action": payload["action"], "text": reply if isinstance(reply, str) else json.dumps(reply)}


def _page(**replies: Any):
    script = ScriptedBrowser(**replies)
    host = FakeHost({"browser.call": script})
    return host, script


class ParserTest(unittest.TestCase):
    def test_snapshot_nodes(self) -> None:
        nodes = parse_snapshot(TREE + '\n  - StaticText "x"\nnoise')
        self.assertEqual([n.role for n in nodes], ["heading", "button", "button", "textbox", "StaticText"])
        self.assertEqual(nodes[0].level, 1)
        self.assertEqual(nodes[3].value, "a@b.c")
        self.assertEqual(nodes[3].target, "@e4")
        self.assertEqual(nodes[4].depth, 1)
        self.assertIsNone(nodes[4].ref)

    def test_typed_replies(self) -> None:
        self.assertEqual(parse_console({"messages": [{"type": "error", "text": "x"}]})[0].type, "error")
        self.assertEqual(parse_console("plain text")[0].text, "plain text")
        self.assertEqual(parse_console(json.dumps({"messages": []})), ())
        error = parse_page_errors(json.dumps({"errors": [{"text": "boom", "line": 3, "column": 1, "url": None}]}))[0]
        self.assertEqual((error.text, error.line), ("boom", 3))
        requests = parse_requests(json.dumps({"requests": [{"url": "a", "status": 200}, {"url": "b"}, {"url": "c", "status": 404}]}))
        self.assertEqual([r.ok for r in requests], [True, False, False])
        tab = parse_tabs(json.dumps({"tabs": [{"tabId": "t1", "url": "u", "title": "T", "active": True}]}))[0]
        self.assertEqual((tab.id, tab.active), ("t1", True))
        diff = parse_diff(json.dumps({"changed": True, "additions": 2, "removals": 1, "diff": "+a"}))
        self.assertEqual((diff.additions, str(diff)), (2, "+a"))


class ElementTest(unittest.TestCase):
    def test_find_all_and_find_one(self) -> None:
        host, _ = _page(snapshot=TREE)
        with host as active:
            with active.client:
                page = browser.page()
                self.assertEqual(len(page.find_all(role="button", name="Save")), 2)
                self.assertEqual([n.name for n in page.find_all(contains="mail")], ["Email"])
                self.assertEqual(page.find_one(role="button", name="Save", nth=1).ref, "e3")
                with self.assertRaises(AgentError) as caught:
                    page.find_one(role="link", name="Home")
                self.assertEqual(caught.exception.kind, "not_found")
                self.assertIn("button 'Save'", caught.exception.message)

    def test_stale_ref_is_resolved_and_retried(self) -> None:
        host, script = _page(
            snapshot=[TREE, TREE.replace("ref=e2", "ref=e9")],
            click=[RuntimeError("Unknown ref: e2"), "clicked"],
        )
        with host as active:
            with active.client:
                page = browser.page()
                element = page.find_one(role="button", name="Save")
                self.assertEqual(element.click(), "clicked")
                self.assertEqual(element.ref, "e9")
        targets = [c.get("target") for c in script.calls if c["action"] == "click"]
        self.assertEqual(targets, ["@e2", "@e9"])

    def test_gone_element_reports_the_original_error(self) -> None:
        host, _ = _page(
            snapshot=[TREE, '- link "Other" [ref=e1]'],
            click=RuntimeError("Unknown ref: e2"),
        )
        with host as active:
            with active.client:
                element = browser.page().find_one(role="button", name="Save")
                with self.assertRaises(AgentError) as caught:
                    element.click()
                self.assertIn("Unknown ref", caught.exception.message)

    def test_refused_calls_are_not_retried(self) -> None:
        host, script = _page(snapshot=TREE, click={"__error__": {"kind": "permission_denied", "message": "no"}})
        with host as active:
            with active.client:
                element = browser.page().find_one(role="button", name="Save")
                with self.assertRaises(AgentError) as caught:
                    element.click()
        self.assertEqual(caught.exception.kind, "permission_denied")
        self.assertEqual(len([c for c in script.calls if c["action"] == "snapshot"]), 1)


class PollingTest(unittest.TestCase):
    def test_until_returns_the_value(self) -> None:
        values = iter([0, "", "done"])
        with FakeHost() as host:
            with host.client:
                self.assertEqual(browser.page().until(lambda: next(values), interval=0.01), "done")

    def test_until_keeps_the_last_error(self) -> None:
        def broken() -> bool:
            raise AgentError("tool_failed", "not yet")

        with FakeHost() as host:
            with host.client:
                with self.assertRaises(AgentError) as caught:
                    browser.page().until(broken, timeout=0.05, interval=0.01)
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertIn("last error: tool_failed: not yet", caught.exception.message)

    def test_until_raises_refusals_at_once(self) -> None:
        def refused() -> bool:
            raise AgentError("unavailable", "off")

        with FakeHost() as host:
            with host.client:
                with self.assertRaises(AgentError) as caught:
                    browser.page().until(refused, timeout=5)
        self.assertEqual(caught.exception.kind, "unavailable")

    def test_wait_gone_and_count(self) -> None:
        host, _ = _page(get=[json.dumps({"text": "Loading"}), json.dumps({"text": "Ready"})])
        with host as active:
            with active.client:
                self.assertEqual(browser.page().wait_gone("Loading", timeout=2), "Loading")


class ExtractionTest(unittest.TestCase):
    def test_table_builds_rows_from_headers(self) -> None:
        reply = {"result": {"head": True, "rows": [["Name", "Qty"], ["apple", "3"]]}}
        host, _ = _page(evaluate=reply)
        with host as active:
            with active.client:
                self.assertEqual(browser.page().table(), [{"Name": "apple", "Qty": "3"}])

    def test_table_without_headers_uses_positions(self) -> None:
        host, _ = _page(evaluate={"result": {"head": False, "rows": [["a", "b"]]}})
        with host as active:
            with active.client:
                self.assertEqual(browser.page().table(), [{"0": "a", "1": "b"}])

    def test_missing_table_is_not_found(self) -> None:
        host, _ = _page(evaluate={"result": None})
        with host as active:
            with active.client:
                with self.assertRaises(AgentError) as caught:
                    browser.page().table("#nope")
        self.assertEqual(caught.exception.kind, "not_found")

    def test_extract_sends_the_spec(self) -> None:
        host, script = _page(evaluate={"result": {"title": "Hi"}})
        with host as active:
            with active.client:
                self.assertEqual(browser.page().extract({"title": "h1"}), {"title": "Hi"})
        self.assertIn('{"title": "h1"}', script.calls[0]["script"])


class AuditTest(unittest.TestCase):
    def test_report_sorts_problems(self) -> None:
        host, script = _page(
            console={"messages": [{"type": "error", "text": "e"}, {"type": "warning", "text": "w"}, {"type": "log", "text": "l"}]},
            errors={"errors": []},
            network={"requests": [{"url": "a", "status": 200}, {"url": "b", "status": 500}]},
            get=[json.dumps({"url": "http://x/"}), json.dumps({"title": "T"})],
        )
        with host as active:
            with active.client:
                report = browser.page().audit("http://x/")
        self.assertEqual((report.title, report.url), ("T", "http://x/"))
        self.assertEqual(len(report.console_errors), 1)
        self.assertEqual(len(report.console_warnings), 1)
        self.assertEqual([r.url for r in report.failed_requests], ["b"])
        self.assertFalse(report.ok)
        clears = [c for c in script.calls if c.get("clear")]
        self.assertEqual(len(clears), 2)

    def test_clean_page_is_ok(self) -> None:
        host, _ = _page(
            console={"messages": []},
            errors={"errors": []},
            network={"requests": [{"url": "a", "status": 200}]},
            get=[json.dumps({"url": "u"}), json.dumps({"title": "T"})],
        )
        with host as active:
            with active.client:
                self.assertTrue(browser.page().audit().ok)


class FilesAndReplayTest(unittest.TestCase):
    def test_screenshot_save_writes_bytes(self) -> None:
        shot = Screenshot(path="/host/only.png", data="aGVsbG8=")
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "sub", "a.png")
            self.assertEqual(shot.save(target), target)
            with open(target, "rb") as handle:
                self.assertEqual(handle.read(), b"hello")

    def test_screenshot_save_without_bytes_or_path(self) -> None:
        with self.assertRaises(AgentError) as caught:
            Screenshot(path="/nowhere/x.png").save("/tmp/never.png")
        self.assertEqual(caught.exception.kind, "not_found")

    def test_goto_file_builds_a_file_url(self) -> None:
        host, script = _page()
        with host as active:
            with active.client:
                browser.page().goto_file("my page.html")
        url = script.calls[0]["url"]
        self.assertTrue(url.startswith("file:///"))
        self.assertTrue(url.endswith("/my%20page.html"))

    def test_history_becomes_a_replayable_script(self) -> None:
        host, _ = _page(snapshot=TREE)
        with host as active:
            with active.client:
                page = browser.page()
                page.goto("http://x/")
                page.find_one(role="button", name="Save", nth=1).click()
                page.fill("@e4", "a@b.c")
                script = page.to_script()
        self.assertEqual(page.history[0], "page.goto('http://x/')")
        self.assertEqual(page.history[1], "page.find_one(role='button', name='Save', nth=1).click()")
        self.assertIn("# a ref from an earlier snapshot", page.history[2])
        compile(script, "replay.py", "exec")
        self.assertEqual(len(page.history), 3)


if __name__ == "__main__":
    unittest.main()
