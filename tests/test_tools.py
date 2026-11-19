"""Typed module tests against the fake host."""

from __future__ import annotations

import unittest

from agent import agents, fs, mutate, shell, state, web
from agent._errors import AgentError
from agent._types import EditResult, GlobResult, GrepResult, Skill, TaskJob, TaskResult, Text, Todo
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
            self.assertEqual(result.paths, ("src/a.py",))
            self.assertEqual(len(result), 1)
            self.assertEqual([entry.path for entry in result], ["src/a.py"])

    def test_grep(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = fs.grep("TODO", include="*.py")
            self.assertIsInstance(result, GrepResult)
            self.assertEqual(result.matches[0].line, 3)
            self.assertEqual(result.matches[0].text, "TODO")

    def test_text_aliases(self) -> None:
        result = Text("a.py", "one\ntwo", lines=2)
        self.assertEqual(result.total_lines, 2)


class FilesystemAttachmentTest(unittest.TestCase):
    def test_read_image(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = fs.read("x.png")
            self.assertEqual(result.path, "x.png")
            self.assertEqual(result.mime, "image/png")
            self.assertEqual(result.bytes, b"hello")

    def test_fetch_image(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = web.fetch("https://example.com/x.png")
            self.assertEqual(result.kind, "attachment")
            self.assertEqual(result.mime, "image/png")
            self.assertEqual(result.bytes, b"hello")


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

    def test_shell_aliases(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = shell.run("echo ok")
            self.assertEqual(result.exit, 0)
            self.assertEqual(result.exit_code, 0)


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

    def test_task(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = agents.tasks.run("explore", "find the tool catalog")
            self.assertIsInstance(result, TaskResult)
            self.assertEqual(result.session_id, "ses_child_demo")
            self.assertEqual(result.output, "child finished")
            self.assertEqual(result.model, "litellm/prometheus")

    def test_task_start_is_detached(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                job = agents.tasks.start("explore", "find the tool catalog", "catalog")
            self.assertIsInstance(job, TaskJob)
            self.assertEqual(job.session_id, "ses_child_demo")
            self.assertEqual(job.job_id, "ses_child_demo")
            self.assertEqual(job.description, "catalog")
            self.assertEqual(job.status, "running")
            self.assertTrue(job.background)
            self.assertEqual(job.model, "litellm/prometheus")

    def test_background_run_is_refused(self) -> None:
        with self.assertRaises(AgentError) as caught:
            agents.tasks.run("explore", "find it", background=True)
        self.assertEqual(caught.exception.kind, "unavailable")


if __name__ == "__main__":
    unittest.main()
