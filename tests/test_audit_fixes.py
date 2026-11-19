"""Regression tests for bugs found in an SDK audit."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from agent import agent, browser, shell
from agent._errors import AgentError
from agent._types import (
    Screenshot,
    parse_console,
    parse_diff,
    parse_glob,
    parse_grep,
    parse_page_errors,
    parse_patch,
)
from fake_host import FakeHost


class ShellAuditTest(unittest.TestCase):
    def test_timed_out_result_is_not_ok(self) -> None:
        payload = {
            "exit": 0,
            "stdout": "",
            "stderr": "",
            "output": "",
            "truncated": False,
            "timed_out": True,
        }
        with FakeHost({"shell.run": lambda _payload: payload}) as host:
            assert host.client is not None
            with host.client:
                result = shell.run("slow")
                self.assertFalse(result.ok)
                with self.assertRaises(AgentError) as caught:
                    shell.run("slow", check=True)
        self.assertEqual(caught.exception.kind, "timeout")


class ParserAuditTest(unittest.TestCase):
    def test_absent_list_fields_are_tolerated(self) -> None:
        self.assertEqual(parse_glob({"entries": None}).entries, ())
        self.assertEqual(parse_grep({"matches": None}).matches, ())
        self.assertEqual(parse_patch({"files": None}).files, ())

    def test_invalid_json_console_is_not_dropped(self) -> None:
        message = parse_console("{not json")
        self.assertEqual(message[0].text, "{not json")
        error = parse_page_errors("{not json")
        self.assertEqual(error[0].text, "{not json")

    def test_unchanged_diff_text_is_not_changed(self) -> None:
        for text in ("No changes", "unchanged", "(no changes)", ""):
            self.assertFalse(parse_diff(text).changed)
        self.assertTrue(parse_diff("+line").changed)


class ScreenshotAuditTest(unittest.TestCase):
    def test_saving_onto_the_host_path_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "shot.png")
            with open(path, "wb") as handle:
                handle.write(b"png")
            self.assertEqual(Screenshot(path=path).save(path), path)
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(), b"png")


class ExtractionAuditTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_at_inside_a_quoted_selector_is_not_an_attribute(self) -> None:
        scripts = []

        def evaluate(payload: dict) -> dict:
            scripts.append(payload["script"])
            return {"action": "evaluate", "text": json.dumps({"result": {}})}

        with FakeHost({"browser.call": evaluate}) as host:
            assert host.client is not None
            with host.client:
                browser.page().extract({"v": 'input[value="a@b"]'})
        script = scripts[0]
        harness = (
            "const el = {innerText: 'text', getAttribute: (name) => name === 'value' ? 'a@b' : null};"
            "global.document = {querySelector: () => el, querySelectorAll: () => [el]};"
            f"console.log(JSON.stringify(eval({json.dumps(script)})));"
        )
        result = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"v": "text"})


class ReplayAuditTest(unittest.TestCase):
    def test_waits_are_recorded(self) -> None:
        def browser_call(payload: dict) -> dict:
            return {"action": payload["action"], "text": json.dumps({"text": "Ready"})}

        with FakeHost({"browser.call": browser_call}) as host:
            assert host.client is not None
            with host.client:
                page = browser.page()
                page.wait_text("Ready")
                script = page.to_script()
        self.assertIn("page.wait_text('Ready')", script)

    def test_scratch_replay_uses_scratch_and_closes(self) -> None:
        def scratch_call(payload: dict) -> dict:
            if payload["action"] == "get":
                what = payload["what"]
                value = "Example Domain" if what == "title" else "https://example.com"
                return {"action": "get", "text": json.dumps({what: value})}
            return {"action": payload["action"], "text": "ok"}

        with FakeHost({"browser.scratch": scratch_call}) as host:
            assert host.client is not None
            with host.client:
                page = browser.scratch()
                page.goto("https://example.com")
                page.viewport(360, 800)
                script = page.to_script()
        self.assertIn("page = browser.scratch()", script)
        self.assertIn("page.viewport(360, 800)", script)
        self.assertIn("page.close()", script)
        self.assertNotIn("page = browser.page()", script)
        compile(script, "scratch_replay.py", "exec")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "replay.py")
            with open(path, "w") as handle:
                handle.write(script)
            with FakeHost({"browser.scratch": scratch_call}) as host:
                assert host.client is not None
                with host.client:
                    result = agent.run_program(path, host.client)
        self.assertEqual(result, {"title": "Example Domain", "url": "https://example.com"})


if __name__ == "__main__":
    unittest.main()
