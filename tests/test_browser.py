"""Browser page tests against the fake host."""

from __future__ import annotations

import unittest

from agent import browser
from agent._errors import AgentError
from agent._types import Screenshot
from fake_host import FakeHost


class BrowserPageTest(unittest.TestCase):
    def test_navigation_and_snapshot_payloads(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                page = browser.page()
                page.goto("https://example.com")
                page.snapshot(urls=True, compact=True, depth=2, selector="main")

            self.assertEqual(
                host.calls,
                [
                    ("browser.call", {"action": "navigate", "url": "https://example.com"}),
                    (
                        "browser.call",
                        {
                            "action": "snapshot",
                            "full": False,
                            "urls": True,
                            "compact": True,
                            "depth": 2,
                            "selector": "main",
                        },
                    ),
                ],
            )

    def test_reading_and_locators(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                page = browser.page()
                page.text()
                title = page.get("title")
                attribute = page.get("attr", "@e1", name="aria-label")
                styles = page.get("styles", "@e1")
                visible = page.is_("visible", "@e1")
                page.find("role", "button", "click", name="Save", exact=True)
                page.console(clear=True)
                page.errors()

            self.assertEqual(title, "Example Domain")
            self.assertEqual(attribute, "go")
            self.assertEqual(styles, {"display": "block"})
            self.assertTrue(visible)

            self.assertEqual(host.calls[0], ("browser.call", {"action": "read"}))
            self.assertEqual(
                host.calls[1],
                ("browser.call", {"action": "get", "what": "title"}),
            )
            self.assertEqual(
                host.calls[2],
                ("browser.call", {"action": "get", "what": "attr", "target": "@e1", "name": "aria-label"}),
            )
            self.assertEqual(
                host.calls[3],
                ("browser.call", {"action": "get", "what": "styles", "target": "@e1"}),
            )
            self.assertEqual(
                host.calls[4],
                ("browser.call", {"action": "is", "what": "visible", "target": "@e1"}),
            )
            self.assertEqual(
                host.calls[5],
                (
                    "browser.call",
                    {
                        "action": "find",
                        "locator": "role",
                        "text": "button",
                        "what": "click",
                        "name": "Save",
                        "exact": True,
                    },
                ),
            )
            self.assertEqual(host.calls[6], ("browser.call", {"action": "console", "clear": True}))
            self.assertEqual(host.calls[7], ("browser.call", {"action": "errors", "clear": False}))

    def test_actions_waits_and_mouse(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                page = browser.page()
                page.click("@e2")
                page.fill("@e3", "hello")
                page.scroll("down", 500)
                page.keyboard_insert("typed")
                page.wait_text("Saved")
                page.wait_url("**/done")
                page.wait_load("networkidle")
                page.wait_function("window.ready")
                page.wait_state("#spinner", "hidden")
                page.wait_download("/tmp/report.pdf")
                page.mouse_move(100, 200)
                page.mouse_down("left")
                page.mouse_wheel(120, 0)

            self.assertEqual(host.calls[0], ("browser.call", {"action": "click", "target": "@e2"}))
            self.assertEqual(
                host.calls[1],
                ("browser.call", {"action": "fill", "target": "@e3", "text": "hello"}),
            )
            self.assertEqual(host.calls[2], ("browser.call", {"action": "scroll", "text": "down", "px": 500}))
            self.assertEqual(host.calls[3], ("browser.call", {"action": "keyboardinsert", "text": "typed"}))
            self.assertEqual(host.calls[4], ("browser.call", {"action": "waittext", "text": "Saved"}))
            self.assertEqual(host.calls[5], ("browser.call", {"action": "waiturl", "url": "**/done"}))
            self.assertEqual(host.calls[6], ("browser.call", {"action": "waitload", "text": "networkidle"}))
            self.assertEqual(
                host.calls[7],
                ("browser.call", {"action": "waitfn", "script": "window.ready"}),
            )
            self.assertEqual(
                host.calls[8],
                ("browser.call", {"action": "waitstate", "target": "#spinner", "text": "hidden"}),
            )
            self.assertEqual(
                host.calls[9],
                ("browser.call", {"action": "waitdownload", "text": "/tmp/report.pdf"}),
            )
            self.assertEqual(
                host.calls[10],
                ("browser.call", {"action": "mouse", "what": "move", "text": "100 200"}),
            )
            self.assertEqual(
                host.calls[11],
                ("browser.call", {"action": "mouse", "what": "down", "text": "left"}),
            )
            self.assertEqual(
                host.calls[12],
                ("browser.call", {"action": "mouse", "what": "wheel", "text": "120 0"}),
            )

    def test_screenshot_parses_path_mime_and_bytes(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                shot = browser.page().screenshot(path="/tmp/shot.png", full=True)

            self.assertIsInstance(shot, Screenshot)
            self.assertEqual(shot.path, "/tmp/shot.png")
            self.assertEqual(shot.mime, "image/png")
            self.assertEqual(shot.bytes, b"hello")
            self.assertEqual(
                host.calls,
                [("browser.call", {"action": "screenshot", "text": "/tmp/shot.png", "full": True})],
            )

    def test_upload_needs_a_file(self) -> None:
        with self.assertRaises(AgentError) as caught:
            browser.page().upload("@e1")
        self.assertEqual(caught.exception.kind, "invalid_argument")


if __name__ == "__main__":
    unittest.main()
