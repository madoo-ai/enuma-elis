"""Behaviors added because models kept doing them."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

import agent
from agent import browser, shell
from agent._errors import AgentError
from agent._program import run_program
from agent._types import GlobResult, FileEntry, Screenshot, ShellResult, Text
from fake_host import FakeHost


def _run(source: str, client: object = None):
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "program.py")
        with open(path, "w") as handle:
            handle.write(source)
        return run_program(path, client)


class ResultAccessTest(unittest.TestCase):
    def test_dict_style_access(self) -> None:
        shot = Screenshot(path="/tmp/a.png", mime="image/png")
        self.assertEqual(shot["path"], "/tmp/a.png")
        self.assertEqual(shot.get("mime"), "image/png")
        self.assertIsNone(shot.get("nope"))
        self.assertEqual(dict(shot)["path"], "/tmp/a.png")
        with self.assertRaises(KeyError):
            shot["nope"]

    def test_wrong_attribute_lists_fields(self) -> None:
        with self.assertRaises(AttributeError) as caught:
            GlobResult(entries=(FileEntry("a"),)).files
        self.assertIn("Fields: entries, truncated, paths", str(caught.exception))
        self.assertIn("did you mean 'paths'", str(caught.exception))

    def test_synonym_is_suggested(self) -> None:
        with self.assertRaises(AttributeError) as caught:
            GlobResult(entries=()).files
        self.assertIn("did you mean 'paths'", str(caught.exception))

    def test_close_name_is_suggested(self) -> None:
        with self.assertRaises(AttributeError) as caught:
            Text("a", "b").txt
        self.assertIn("did you mean 'text'", str(caught.exception))

    def test_shell_aliases_and_json(self) -> None:
        result = ShellResult(exit=2, stdout="o", stderr="", output="o")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(result.ok)
        self.assertEqual(agent.to_json(result), {"exit": 2, "output": "o", "truncated": False, "timed_out": False})

    def test_write_and_edit_results_have_a_path(self) -> None:
        from agent._types import EditResult, WriteResult

        self.assertEqual(WriteResult(file="a", bytes=1, created=True)["path"], "a")
        self.assertEqual(EditResult("b", 1, 0, 0).path, "b")

    def test_verdicts_are_in_json(self) -> None:
        from agent._types import PageReport, Request

        self.assertEqual(agent.to_json(PageReport("u", "t"))["ok"], True)
        self.assertEqual(agent.to_json(Request("u", status=500))["ok"], False)

    def test_json_drops_empty_fields(self) -> None:
        self.assertEqual(agent.to_json(Text("a", "b")), {"path": "a", "text": "b", "truncated": False, "kind": "file"})


class ShellCommandTest(unittest.TestCase):
    def test_argv_list_is_quoted(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                shell.run(["git", "commit", "-m", "it's a test"])
            self.assertEqual(host.calls[0][1]["command"], "git commit -m 'it'\"'\"'s a test'")


class ProgramLoaderTest(unittest.TestCase):
    def test_script_without_run_is_wrapped(self) -> None:
        self.assertEqual(_run("import os\nx = 2\nreturn {'x': x}\n"), {"x": 2})

    def test_trailing_expression_is_returned(self) -> None:
        self.assertEqual(_run("x = 20\nx + 1\n"), 21)

    def test_modules_are_in_scope(self) -> None:
        self.assertIs(_run("def Run(ctx, a):\n    return browser\n"), browser)

    def test_module_aliases_import(self) -> None:
        source = "import fs\nfrom agents import tasks\ndef Run(ctx, a):\n    return [fs.read.__name__, tasks.start.__name__]\n"
        self.assertEqual(_run(source), ["read", "start"])

    def test_agent_names_are_in_scope(self) -> None:
        self.assertEqual(_run("def Run(ctx, a):\n    return [agent.__name__, AgentError.__name__]\n"), ["agent", "AgentError"])

    def test_aliases_do_not_shadow_real_modules(self) -> None:
        self.assertIs(_run("import os\ndef Run(ctx, a):\n    return os\n"), os)

    def test_failure_keeps_program_line(self) -> None:
        try:
            _run("def Run(ctx, a):\n    return {}['k']\n")
        except KeyError as error:
            self.assertIn("{}['k']", agent.to_error(error)["trace"])
        else:
            self.fail("expected KeyError")

    def test_client_exposes_modules(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            self.assertIs(host.client.jobs, agent.jobs)
            self.assertIs(host.client.fs, sys.modules["agent.fs"])
            with self.assertRaises(AttributeError):
                host.client.nope


class HelpTest(unittest.TestCase):
    def test_dir_lists_only_the_api(self) -> None:
        self.assertNotIn("Any", dir(agent.fs))
        self.assertEqual(dir(agent.fs), ["glob", "grep", "read"])

    def test_help_shows_signatures(self) -> None:
        text = agent.help("shell")
        self.assertIn("shell.run(command", text)
        self.assertIn("timeout", text)
        self.assertNotIn("'str'", text)
        self.assertIn("page.goto", agent.help("browser"))
        self.assertIn("unknown module", agent.help("nope"))


class BrowserErgonomicsTest(unittest.TestCase):
    def test_get_title_ignores_a_target(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                page = browser.page()
                self.assertEqual(page.get("title", "title"), "Example Domain")
                self.assertEqual(page.title(), "Example Domain")
            self.assertEqual(host.calls[0], ("browser.call", {"action": "get", "what": "title"}))

    def test_scroll_rejects_a_number(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                with self.assertRaises(AgentError) as caught:
                    browser.page().scroll(0, 0)
            self.assertEqual(caught.exception.kind, "invalid_argument")
            self.assertEqual(host.calls, [])

    def test_wait_text_times_out_with_a_clear_error(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                with self.assertRaises(AgentError) as caught:
                    browser.page().wait_text("never", timeout=0.3)
            self.assertEqual(caught.exception.kind, "timeout")

    def test_numbers_become_strings_for_text_fields(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                browser.page().wait_ms(500)
                browser.page().press(13)
            self.assertEqual(host.calls[0][1]["text"], "500")
            self.assertEqual(host.calls[1][1]["text"], "13")


if __name__ == "__main__":
    unittest.main()
