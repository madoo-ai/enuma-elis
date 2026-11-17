"""Typed module tests against the fake host."""

from __future__ import annotations

import unittest

from agent import fs, mutate, shell, state, web
from agent._errors import AgentError
from agent._types import EditResult, GlobResult, GrepResult, Skill, Todo
from fake_host import FakeHost


class FilesystemReadTest(unittest.TestCase):
    def test_glob(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = fs.glob("**/*.py", path="src")
            self.assertIsInstance(result, GlobResult)
            self.assertEqual(result.entries[0].path, "src/a.py")
            self.assertFalse(result.truncated)

    def test_grep(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = fs.grep("TODO", include="*.py")
            self.assertIsInstance(result, GrepResult)
            self.assertEqual(result.matches[0].line, 3)
            self.assertEqual(result.matches[0].text, "TODO")


class FilesystemWriteTest(unittest.TestCase):
    def test_edit(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = mutate.edit("src/a.py", "old", "new")
            self.assertIsInstance(result, EditResult)
            self.assertEqual(result.replacements, 1)
            self.assertIn("--- a", result.patch)

    def test_write(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = mutate.write("src/a.py", "hello")
            self.assertEqual(result.file, "src/a.py")
            self.assertEqual(result.bytes, 5)
            self.assertTrue(result.created)

    def test_patch(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = mutate.patch("*** Begin Patch\n*** End Patch")
            self.assertEqual(result.files, ("src/a.py",))


class ProcessTest(unittest.TestCase):
    def test_run(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = shell.run("echo ok")
            self.assertEqual(result.exit, 0)
            self.assertEqual(result.stdout, "ok\n")
            self.assertFalse(result.timed_out)

    def test_check_raises(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                with self.assertRaises(AgentError) as caught:
                    shell.run("false", check=True)
            self.assertEqual(caught.exception.kind, "tool_failed")


class NetworkTest(unittest.TestCase):
    def test_fetch(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = web.fetch("https://example.com")
            self.assertEqual(result.url, "https://example.com")
            self.assertEqual(result.text, "page")

    def test_search(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = web.search("python code mode", num_results=3)
            self.assertEqual(result.query, "python code mode")
            self.assertEqual(result.provider, "exa")


class StateTest(unittest.TestCase):
    def test_skill(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = state.skills.load("ste-writing")
            self.assertIsInstance(result, Skill)
            self.assertEqual(result.directory, "/skills/example")

    def test_todos(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = state.todos.write([Todo("write tests", "pending", "high")])
            self.assertEqual(result[0].content, "write tests")
            self.assertEqual(result[0].priority, "high")


if __name__ == "__main__":
    unittest.main()
