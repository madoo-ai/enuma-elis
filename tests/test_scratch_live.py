"""A real scratch Chromium: emulation, interception, storage, and lifecycle.

Opt in with ``AGENT_BROWSER_LIVE=1``. The shim starts its own isolated session.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest

from agent import browser
from agent._errors import AgentError
from fake_host import FakeHost

LIVE = os.environ.get("AGENT_BROWSER_LIVE") == "1" and shutil.which("agent-browser")

PAGE = """<!doctype html><title>Scratch</title>
<h1>Wide</h1><input aria-label="Email"><button id=go>Add</button>
<ul id=list></ul>
<script>
document.getElementById('go').onclick = () => {
  const li = document.createElement('li'); li.textContent = 'one';
  document.getElementById('list').appendChild(li);
};
</script>"""



@unittest.skipUnless(LIVE, "set AGENT_BROWSER_LIVE=1 with agent-browser installed")
class ScratchLiveTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = tempfile.mkdtemp(prefix="enuma-scratch-page-")
        with open(os.path.join(cls.dir, "index.html"), "w") as handle:
            handle.write(PAGE)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=cls.dir)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/index.html"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self) -> None:
        import live_browser_host

        self.shim = live_browser_host
        self.host = FakeHost({"browser.scratch": live_browser_host.scratch_call})
        self.host.__enter__()
        self.host.client.__enter__()
        self.page = browser.scratch()

    def tearDown(self) -> None:
        try:
            self.page.close()
        except AgentError:
            pass
        self.host.client.__exit__(None, None, None)
        self.host.__exit__(None, None, None)

    def test_page_helpers_work_on_scratch(self) -> None:
        self.page.goto(self.url)
        self.page.find_one(role="button", name="Add").click()
        self.assertEqual(self.page.extract({"items": "li[]"})["items"], ["one"])
        self.assertTrue(self.page.audit().ok)

    def test_viewport_changes_the_layout(self) -> None:
        self.page.viewport(360, 800)
        self.page.goto(self.url)
        self.assertEqual(self.page.evaluate("window.innerWidth"), 360)
        self.page.viewport(1280, 720)
        self.assertEqual(self.page.evaluate("window.innerWidth"), 1280)

    def test_route_blocks_requests(self) -> None:
        self.page.goto(self.url)
        blocked = self.url.replace("index.html", "blocked")
        self.page.route(blocked)
        self.page.evaluate(
            "window.__r = null; fetch('/blocked').then(() => window.__r = 'loaded')"
            ".catch(() => window.__r = 'failed'); 1"
        )
        self.assertEqual(self.page.until(lambda: self.page.evaluate("window.__r"), timeout=10), "failed")
        self.page.unroute(blocked)

    def test_offline_stops_requests(self) -> None:
        self.page.goto(self.url)
        self.page.offline(True)
        value = self.page.evaluate("navigator.onLine")
        self.assertFalse(value)
        self.page.offline(False)

    def test_cookies_and_storage_are_private_and_writable(self) -> None:
        self.page.goto(self.url)
        self.assertEqual(self.page.cookies(), [])
        self.page.set_cookie("seen", "yes", url=self.url)
        cookies = self.page.cookies()
        self.assertTrue(any(c.get("name") == "seen" for c in cookies))
        self.page.set_storage("theme", "dark")
        self.assertEqual(self.page.evaluate("localStorage.getItem('theme')"), "dark")
        self.assertEqual(self.page.storage(key="theme"), "dark")
        self.page.clear_storage()
        self.assertIsNone(self.page.evaluate("localStorage.getItem('theme')"))
        self.page.clear_cookies()

    def test_tabs_can_be_closed(self) -> None:
        self.page.goto(self.url)
        self.page.tab_new("about:blank")
        self.assertEqual(len(self.page.tab_list()), 2)
        self.page.tab_close()
        self.assertEqual(len(self.page.tab_list()), 1)

    def test_close_ends_the_browser(self) -> None:
        self.page.goto(self.url)
        self.page.close()
        with self.assertRaises(AgentError) as caught:
            self.page.goto(self.url)
        self.assertEqual(caught.exception.kind, "unavailable")


if __name__ == "__main__":
    unittest.main()
