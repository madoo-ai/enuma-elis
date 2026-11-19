"""Regression tests for a second SDK audit pass."""

from __future__ import annotations

import unittest

import agent
from agent._types import parse_snapshot


class SerializationAuditTest(unittest.TestCase):
    def test_cyclic_lists_are_rejected(self) -> None:
        value = ["ok"]
        value.append(value)
        with self.assertRaises(agent.AgentError) as caught:
            agent.to_json(value)
        self.assertEqual(caught.exception.kind, "invalid_result")
        self.assertIn("cyclic value at result[1]", caught.exception.message)

    def test_cyclic_dicts_are_rejected(self) -> None:
        value = {"text": "x"}
        value["self"] = value
        with self.assertRaises(agent.AgentError) as caught:
            agent.to_json(value)
        self.assertIn("cyclic value at result['self']", caught.exception.message)

    def test_repeated_but_acyclic_values_serialize(self) -> None:
        child = {"a": 1}
        self.assertEqual(agent.to_json([child, child]), [{"a": 1}, {"a": 1}])


class SnapshotAuditTest(unittest.TestCase):
    def test_snapshot_names_are_json_unescaped(self) -> None:
        raw = r'- button "say \"hi\"\nnext" [ref=e1]'
        node = parse_snapshot(raw)[0]
        self.assertEqual(node.name, 'say "hi"\nnext')
        self.assertEqual(node.ref, "e1")


if __name__ == "__main__":
    unittest.main()
