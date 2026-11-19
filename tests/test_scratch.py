"""Scratch browser SDK against a scripted host."""

from __future__ import annotations

import json
import unittest

from agent import browser
from agent._errors import AgentError
from fake_host import FakeHost


def _host():
    return FakeHost({"browser.scratch": lambda payload: {"action": payload["action"], "text": json.dumps({"ok": 1})}})


class ScratchSdkTest(unittest.TestCase):
    def test_uses_the_scratch_tool_and_session(self) -> None:
        with _host() as host:
            with host.client:
                page = browser.scratch()
                self.assertEqual(page.tool, "browser.scratch")
                page.goto("https://x/")
            tool, payload = host.calls[0]
            self.assertEqual(tool, "browser.scratch")
            self.assertRegex(payload["session"], r"^enuma-scratch-[a-f0-9]{8}$")

    def test_repeated_calls_share_one_browser(self) -> None:
        self.assertEqual(browser.scratch().session, browser.scratch().session)

    def test_fs_write_points_at_mutate(self) -> None:
        from agent import fs

        with self.assertRaises(AttributeError) as caught:
            fs.write
        self.assertIn("use mutate.write", str(caught.exception))

    def test_shared_page_uses_the_shared_tool(self) -> None:
        self.assertEqual(browser.page().tool, "browser.call")
        self.assertIsNone(browser.page().session)

    def test_scratch_page_has_the_page_helpers(self) -> None:
        with _host() as host:
            with host.client:
                page = browser.scratch()
                page.find_one  # noqa: B018  (attribute exists)
                page.extract  # noqa: B018
                self.assertTrue(callable(page.audit))
                self.assertFalse(hasattr(browser.page(), "viewport"))
                self.assertFalse(hasattr(browser.page(), "route"))

    def test_viewport_and_emulation_arguments(self) -> None:
        with _host() as host:
            with host.client:
                page = browser.scratch()
                page.viewport(360, 800)
                page.viewport(360, 800, 2)
                page.device("iPhone 12")
                page.geo(37.7749, -122.4194)
                page.offline()
                page.offline(False)
                page.media("dark", reduced_motion=True)
                page.headers({"X-Test": "1"})
            commands = [(payload["action"], payload.get("text"), payload.get("what")) for _, payload in host.calls]
            self.assertEqual(commands[0], ("viewport", "360 800", None))
            self.assertEqual(commands[1], ("viewport", "360 800 2", None))
            self.assertEqual(commands[2], ("device", "iPhone 12", None))
            self.assertEqual(commands[3], ("geo", "37.7749 -122.419", None))
            self.assertEqual(commands[4], ("offline", None, "on"))
            self.assertEqual(commands[5], ("offline", None, "off"))
            self.assertEqual(commands[6], ("media", None, "dark"))
            self.assertEqual(json.loads(host.calls[7][1]["text"]), {"X-Test": "1"})

    def test_route_arguments(self) -> None:
        with _host() as host:
            with host.client:
                page = browser.scratch()
                page.route("**/api")
                page.route("**/api", resource_type="fetch")
                page.unroute("**/api")
            self.assertEqual(host.calls[0][1]["what"], "abort")
            self.assertEqual(host.calls[1][1]["selector"], "fetch")
            self.assertEqual(host.calls[2][1]["action"], "unroute")

    def test_cookies_and_storage(self) -> None:
        with _host() as host:
            with host.client:
                page = browser.scratch()
                page.cookies()
                page.set_cookie("a", "1", url="https://x/")
                page.clear_cookies()
                page.storage()
                page.set_storage("k", "v", kind="session")
                page.clear_storage("session")
            payloads = [payload for _, payload in host.calls]
            self.assertEqual(payloads[0]["what"], "get")
            self.assertEqual((payloads[1]["name"], payloads[1]["text"], payloads[1]["url"]), ("a", "1", "https://x/"))
            self.assertEqual(payloads[2]["what"], "clear")
            self.assertEqual(payloads[3]["locator"], "local")
            self.assertEqual((payloads[4]["locator"], payloads[4]["name"]), ("session", "k"))
            self.assertEqual(payloads[5]["what"], "clear")

    def test_close_disables_the_handle(self) -> None:
        with _host() as host:
            with host.client:
                page = browser.scratch()
                page.close()
                with self.assertRaises(AgentError) as caught:
                    page.goto("https://x/")
                self.assertEqual(caught.exception.kind, "unavailable")
                self.assertEqual(page.close(), "already closed")
            self.assertEqual(len(host.calls), 1)


if __name__ == "__main__":
    unittest.main()
