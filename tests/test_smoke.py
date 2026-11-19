"""Zero-dependency smoke tests for the SDK surface."""

from __future__ import annotations

import unittest

import agent
from agent._types import FetchResult, Image, Screenshot, Text


class SmokeTest(unittest.TestCase):
    def test_version(self) -> None:
        self.assertEqual(agent.__version__, "0.1.0")

    def test_modules_import(self) -> None:
        from agent import fs, mutate, shell, state, web

        for module in (fs, mutate, shell, web, state):
            self.assertIsNotNone(module)

    def test_error(self) -> None:
        error = agent.AgentError("permission_denied", "grep denied")
        self.assertEqual(str(error), "permission_denied: grep denied")
        self.assertEqual(error.args, ("grep denied",))

    def test_to_json(self) -> None:
        value = agent.to_json({"text": Text("a.go", "package a\n")})
        self.assertEqual(value, {"text": {"path": "a.go", "text": "package a\n", "truncated": False, "kind": "file"}})

    def test_to_json_marks_a_screenshot(self) -> None:
        value = agent.to_json(Screenshot("/tmp/shot.png", "image/png", "aGVsbG8="))
        self.assertEqual(
            value,
            {
                "__agent_kind__": "screenshot",
                "path": "/tmp/shot.png",
                "mime": "image/png",
                "data": "aGVsbG8=",
            },
        )

    def test_to_json_marks_native_attachments(self) -> None:
        self.assertEqual(
            agent.to_json(Image("x.png", "image/png", "aGVsbG8=")),
            {
                "__agent_kind__": "attachment",
                "path": "x.png",
                "mime": "image/png",
                "data": "aGVsbG8=",
            },
        )
        self.assertEqual(
            agent.to_json(
                FetchResult(
                    "https://example.com/x.png",
                    "Image fetched successfully",
                    kind="attachment",
                    mime="image/png",
                    data="aGVsbG8=",
                )
            ),
            {
                "__agent_kind__": "attachment",
                "path": "https://example.com/x.png",
                "url": "https://example.com/x.png",
                "mime": "image/png",
                "data": "aGVsbG8=",
                "text": "Image fetched successfully",
                "title": "",
            },
        )

    def test_to_json_rejects_unknown(self) -> None:
        with self.assertRaises(agent.AgentError) as caught:
            agent.to_json({1, 2, 3})
        self.assertEqual(caught.exception.kind, "invalid_result")

    def test_to_json_names_the_bad_value(self) -> None:
        with self.assertRaises(agent.AgentError) as caught:
            agent.to_json({"ids": [1, {2}]})
        self.assertIn("set at result['ids'][1]", caught.exception.message)
        self.assertIn("list(...)", caught.exception.message)

    def test_to_json_converts_nested_results(self) -> None:
        from agent._types import FileEntry, GlobResult

        self.assertEqual(
            agent.to_json({"found": GlobResult(entries=(FileEntry("a"),))}),
            {"found": {"entries": [{"path": "a", "type": "file"}], "truncated": False}},
        )

    def test_to_error_reports_the_failing_program_line(self) -> None:
        def Run():
            return {}["missing"]

        try:
            Run()
        except KeyError as error:
            body = agent.to_error(error)
        self.assertEqual(body["kind"], "exception")
        self.assertEqual(body["message"], "KeyError: 'missing'")
        self.assertIn("in Run", body["trace"])
        self.assertIn('{}["missing"]', body["trace"])

    def test_agent_is_exported(self) -> None:
        from agent import agent as package

        self.assertIs(package, agent)

    def test_to_error(self) -> None:
        self.assertEqual(
            agent.to_error(agent.AgentError("not_found", "missing")),
            {"kind": "not_found", "message": "missing", "data": None},
        )


if __name__ == "__main__":
    unittest.main()
