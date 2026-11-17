"""Zero-dependency smoke tests for the SDK surface."""

from __future__ import annotations

import unittest

import agent
from agent._types import Text


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
        self.assertEqual(value, {"text": {"path": "a.go", "text": "package a\n", "lines": None, "truncated": False, "kind": "file"}})

    def test_to_json_rejects_unknown(self) -> None:
        with self.assertRaises(agent.AgentError) as caught:
            agent.to_json({1, 2, 3})
        self.assertEqual(caught.exception.kind, "invalid_result")

    def test_to_error(self) -> None:
        self.assertEqual(
            agent.to_error(agent.AgentError("not_found", "missing")),
            {"kind": "not_found", "message": "missing", "data": None},
        )


if __name__ == "__main__":
    unittest.main()
