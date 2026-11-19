"""Run the browser helpers against a real Chromium.

Opt in with ``AGENT_BROWSER_LIVE=1``; it needs ``agent-browser`` on PATH and
starts its own private browser session.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
import urllib.parse

from agent import browser
from agent._errors import AgentError
from fake_host import FakeHost

LIVE = os.environ.get("AGENT_BROWSER_LIVE") == "1" and shutil.which("agent-browser")

PAGE = """<!doctype html><title>Live Page</title>
<h1>Hello</h1><h2>Sub</h2>
<label for=email>Email</label><input id=email name=email>
<button id=add onclick="
  const li = document.createElement('li'); li.textContent = 'item ' + (document.querySelectorAll('li').length + 1);
  document.getElementById('list').appendChild(li);
  document.getElementById('status').textContent = 'added';">Add</button>
<button id=alert onclick="alert('careful')">Alert</button>
<button id=swap onclick="
  const b = document.getElementById('add'); const c = b.cloneNode(true);
  b.replaceWith(c);">Rebuild</button>
<ul id=list></ul><p id=status>idle</p>
<a class=more href="/next">Next page</a>
<table id=t><tr><th>Name</th><th>Qty</th></tr><tr><td>apple</td><td>3</td></tr><tr><td>pear</td><td>5</td></tr></table>
<form action="/submit" method=post><input name=q aria-label="Query" value="x"></form>
<script>console.log('hello log'); console.error('bad log'); setTimeout(() => { throw new Error('boom'); }, 20);
fetch('http://127.0.0.1:9/missing').catch(() => {});</script>"""
URL = "data:text/html," + urllib.parse.quote(PAGE)


@unittest.skipUnless(LIVE, "set AGENT_BROWSER_LIVE=1 with agent-browser installed")
class LiveBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import live_browser_host

        cls.shim = live_browser_host
        cls.host = FakeHost({"browser.call": live_browser_host.browser_call})
        cls.host.__enter__()
        assert cls.host.client is not None
        cls.host.client.__enter__()
        cls.page = browser.page()
        cls.page.goto(URL)
        cls.page.wait_text("Hello")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.host.client.__exit__(None, None, None)
        cls.host.__exit__(None, None, None)
        cls.shim.close_session()

    def test_nodes_and_find(self) -> None:
        nodes = self.page.nodes(full=True)
        roles = {node.role for node in nodes}
        self.assertIn("button", roles)
        add = self.page.find_all(role="button", name="Add")
        self.assertEqual(len(add), 1)
        self.assertTrue(add[0].ref)
        self.assertTrue(add[0].target.startswith("@e"))
        with self.assertRaises(AgentError) as caught:
            self.page.find_one(role="button", name="Nope")
        self.assertEqual(caught.exception.kind, "not_found")
        self.assertIn("button 'Add'", caught.exception.message)

    def test_element_actions_and_stale_ref_recovery(self) -> None:
        add = self.page.find_one(role="button", name="Add")
        add.click()
        self.assertIn("item 1", self.page.get("text", "#list"))
        old = add.ref
        self.page.reload()
        self.page.wait_text("Hello")
        add.click()  # a reload drops the refs, so this ref is stale
        self.assertEqual(self.page.get("count", "#list li"), 1)
        self.assertTrue(add.ref)

    def test_find_fill_with_input(self) -> None:
        self.page.find("label", "Email", "fill", input="a@b.c")
        self.assertEqual(self.page.get("value", "#email"), "a@b.c")

    def test_typed_lists(self) -> None:
        self.page.until(lambda: self.page.errors(), timeout=5)
        console = self.page.console()
        self.assertTrue(any(m.type == "error" and m.text == "bad log" for m in console))
        self.assertTrue(any(e.text.startswith("Error: boom") for e in self.page.errors()))
        requests = self.page.network()
        self.assertTrue(any(r.url.startswith("data:") and r.ok for r in requests))
        self.assertTrue(any("127.0.0.1:9" in r.url and not r.ok for r in requests))
        tabs = self.page.tab_list()
        self.assertTrue(tabs[0].id.startswith("t"))
        self.assertTrue(any(tab.active for tab in tabs))

    def test_audit_reports_problems(self) -> None:
        report = self.page.audit()
        self.assertEqual(report.title, "Live Page")
        self.assertFalse(report.ok)
        self.assertTrue(report.console_errors)
        self.assertTrue(report.failed_requests)

    def test_extraction(self) -> None:
        links = self.page.links()
        self.assertEqual(links[0]["text"], "Next page")
        self.assertEqual([h["text"] for h in self.page.headings()], ["Hello", "Sub"])
        self.assertEqual(self.page.table("#t"), [{"Name": "apple", "Qty": "3"}, {"Name": "pear", "Qty": "5"}])
        forms = self.page.forms()
        self.assertEqual(forms[0]["method"], "post")
        self.assertEqual(forms[0]["fields"][0]["label"], "Query")
        data = self.page.extract({"title": "h1", "href": "a.more@href", "heads": "h1[]", "none": ".zzz"})
        self.assertEqual(data["title"], "Hello")
        self.assertTrue(data["href"].endswith("/next") or data["href"] == "/next")
        self.assertEqual(data["heads"], ["Hello"])
        self.assertIsNone(data["none"])

    def test_evaluate_returns_values(self) -> None:
        self.assertEqual(self.page.evaluate("1 + 1"), 2)
        self.assertEqual(self.page.evaluate("({a: [1, 2]})"), {"a": [1, 2]})
        self.assertEqual(self.page.title(), "Live Page")

    def test_wait_helpers(self) -> None:
        self.assertEqual(self.page.wait_count("h1", 1), 1)
        with self.assertRaises(AgentError) as caught:
            self.page.wait_text("never appears", timeout=0.5)
        self.assertEqual(caught.exception.kind, "timeout")
        element = self.page.wait_for(role="textbox", name="Email", timeout=5)
        self.assertEqual(element.role, "textbox")

    def test_screenshot_save_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "shot.png")
            shot = self.page.screenshot(save=path)
            self.assertTrue(os.path.getsize(path) > 100)
            self.assertEqual(shot.path.endswith(".png"), True)
        script = self.page.to_script()
        compile(script, "replay.py", "exec")
        self.assertIn("page.find_one(role='button', name='Add').click()", script)


if __name__ == "__main__":
    unittest.main()
