"""Bridge and typed read tests against the fake host."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor

from agent import AgentError, fs
from agent._types import Text
from fake_host import FakeHost


class BridgeTest(unittest.TestCase):
    def test_handshake(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            self.assertEqual(host.client.protocol, 1)
            self.assertIn("fs.read", host.client.tools)
            self.assertEqual(host.client.limits["concurrency"], 8)

    def test_read(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                result = fs.read("README.md", limit=10)
            self.assertIsInstance(result, Text)
            self.assertEqual(result.path, "README.md")
            self.assertEqual(result.text, "hello\n")
            self.assertFalse(result.truncated)

    def test_error(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                with self.assertRaises(AgentError) as caught:
                    host.client.call("test.fail", {})
            self.assertEqual(caught.exception.kind, "permission_denied")
            self.assertEqual(str(caught.exception), "permission_denied: nope")

    def test_unknown_tool(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                with self.assertRaises(AgentError) as caught:
                    host.client.call("nope.missing", {})
            self.assertEqual(caught.exception.kind, "unavailable")

    def test_concurrent_calls(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(
                        pool.map(
                            lambda index: host.client.call("test.echo", {"index": index}),
                            range(8),
                        )
                    )
            self.assertEqual([item["index"] for item in results], list(range(8)))

    def test_timeout(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                with self.assertRaises(AgentError) as caught:
                    host.client.call("test.sleep", {"seconds": 0.2}, timeout=0.05)
            self.assertEqual(caught.exception.kind, "timeout")


if __name__ == "__main__":
    unittest.main()
