"""Zero-dependency smoke tests for the skeleton."""

from __future__ import annotations

import unittest

import agent


class SmokeTest(unittest.TestCase):
    def test_version(self) -> None:
        self.assertEqual(agent.__version__, "0.0.0")

    def test_modules_import(self) -> None:
        from agent import fs, mutate, shell, state, web

        for module in (fs, mutate, shell, web, state):
            self.assertIsNotNone(module)

    def test_error(self) -> None:
        error = agent.AgentError("permission_denied", "grep denied")
        self.assertEqual(str(error), "permission_denied: grep denied")
        self.assertEqual(error.args, ("grep denied",))

    def test_client_shape(self) -> None:
        with agent.Client() as client:
            with self.assertRaises(NotImplementedError):
                client.call("fs.read", {"path": "README.md"})


if __name__ == "__main__":
    unittest.main()
