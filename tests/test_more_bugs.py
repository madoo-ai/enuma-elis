"""Regression tests for a second SDK audit pass."""

from __future__ import annotations

import unittest

import agent
from agent import browser
from agent._types import parse_snapshot
from fake_host import FakeHost


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


class NumericAuditTest(unittest.TestCase):
    def test_malformed_numbers_do_not_crash(self) -> None:
        from agent._types import parse_diff, parse_edit, parse_grep, parse_shell, parse_write

        self.assertEqual(parse_grep({"matches": [{"line": {"x": 1}, "path": "a", "text": "x"}]}).matches[0].line, 0)
        self.assertEqual(parse_edit({"additions": None}).additions, 0)
        self.assertEqual(parse_write({"bytes": "bad"}).bytes, 0)
        self.assertEqual(parse_shell({"exit": ["x"]}).exit, 0)
        self.assertEqual(parse_diff({"additions": "bad"}).additions, 0)

    def test_nonfinite_floats_are_rejected(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(agent.AgentError) as caught:
                agent.to_json(value)
            self.assertEqual(caught.exception.kind, "invalid_result")
            self.assertIn("non-finite float", caught.exception.message)
        self.assertEqual(agent.to_json(1.5), 1.5)

    def test_request_status_is_normalized(self) -> None:
        from agent._types import parse_requests

        request = parse_requests({"requests": [{"url": "u", "status": "500"}]})[0]
        self.assertEqual(request.status, 500)
        self.assertFalse(request.ok)


class BridgeAuditTest(unittest.TestCase):
    def test_a_failed_write_is_reported_as_canceled(self) -> None:
        import threading

        from agent._bridge import Bridge

        release = threading.Event()

        class BlockingReader:
            def readline(self) -> bytes:
                release.wait(1.0)
                return b""

            def close(self) -> None:
                pass

        class BrokenWriter:
            def write(self, _data: bytes) -> int:
                raise ValueError("closed")

            def flush(self) -> None:
                pass

            def close(self) -> None:
                pass

        bridge = Bridge(BlockingReader(), BrokenWriter(), close_reader=False, close_writer=False)
        try:
            with self.assertRaises(agent.AgentError) as caught:
                bridge.send({"type": "call", "id": "x", "tool": "x", "input": {}})
            self.assertEqual(caught.exception.kind, "canceled")
        finally:
            release.set()
            bridge.close()


class HelpAuditTest(unittest.TestCase):
    def test_help_lists_scratch_and_element_apis(self) -> None:
        text = agent.help("browser")
        self.assertIn("scratch.viewport", text)
        self.assertIn("scratch.close", text)
        self.assertIn("element.click", text)
        self.assertIn("page.goto", text)


class ActiveClientAuditTest(unittest.TestCase):
    def test_nested_clients_restore_the_outer_client(self) -> None:
        outer = agent.Client.__new__(agent.Client)
        inner = agent.Client.__new__(agent.Client)
        agent._set_active(outer)
        agent._set_active(inner)
        self.assertIs(agent.current_client(), inner)
        agent._clear_active(inner)
        self.assertIs(agent.current_client(), outer)
        agent._clear_active(outer)
        with self.assertRaises(agent.AgentError):
            agent.current_client()


class ScratchStorageAuditTest(unittest.TestCase):
    def test_storage_kind_is_validated_before_a_call(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                page = browser.scratch()
                with self.assertRaises(agent.AgentError) as caught:
                    page.storage(kind="sessionstorage")
                self.assertEqual(caught.exception.kind, "invalid_argument")
                with self.assertRaises(agent.AgentError):
                    page.set_storage("k", "v", kind="cookie")
                with self.assertRaises(agent.AgentError):
                    page.clear_storage(kind="localstorage")
        self.assertEqual(host.calls, [])


class TraceAuditTest(unittest.TestCase):
    def test_tool_error_trace_is_program_only(self) -> None:
        import os
        import tempfile

        from agent._program import run_program

        source = "def Run(ctx, a):\n    return a.call('test.fail', {})\n"
        with FakeHost() as host:
            assert host.client is not None
            with host.client, tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, "program.py")
                with open(path, "w") as handle:
                    handle.write(source)
                try:
                    run_program(path, host.client)
                except agent.AgentError as error:
                    body = agent.to_error(error)
        self.assertIn("program.py:2 in Run", body["trace"])
        self.assertNotIn("_base.py", body["trace"])

    def test_syntax_error_trace_points_at_the_program(self) -> None:
        import os
        import tempfile

        from agent._program import run_program

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "program.py")
            with open(path, "w") as handle:
                handle.write("x = 1\n    y = 2\n")
            with self.assertRaises(SyntaxError) as caught:
                run_program(path, None)
        body = agent.to_error(caught.exception)
        self.assertIn("program.py:2 in <module>", body["trace"])
        self.assertIn("y = 2", body["trace"])
        self.assertNotIn("ast.py", body["trace"])
