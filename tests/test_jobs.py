"""Generic background call-handle tests against the fake host."""

from __future__ import annotations

import threading
import time
import unittest

from agent import AgentError, fs, jobs
from fake_host import FakeHost


class JobsTest(unittest.TestCase):
    def test_result_and_errors(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                read = jobs.start(fs.read, "README.md", limit=10)
                failed = jobs.start(host.client.call, "test.fail", {})
                self.assertEqual(read.result().text, "hello\n")
                with self.assertRaises(AgentError) as caught:
                    failed.result()
                self.assertEqual(caught.exception.kind, "permission_denied")
            self.assertTrue(jobs.wait_all())

    def test_calls_overlap(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                started = time.monotonic()
                slow = [jobs.start(host.client.call, "test.sleep", {"seconds": 0.1}) for _ in range(4)]
                jobs.gather(*slow)
                elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.32)

    def test_wait_all(self) -> None:
        with FakeHost() as host:
            assert host.client is not None
            with host.client:
                pending = [jobs.start(host.client.call, "test.echo", {"index": index}) for index in range(3)]
                self.assertTrue(jobs.wait_all())
                self.assertEqual([job.result()["index"] for job in pending], [0, 1, 2])

    def test_cancel_a_queued_job(self) -> None:
        release = threading.Event()
        blocker = threading.Event()
        try:
            with FakeHost(handlers={"test.block": lambda payload: blocker.wait(1.0) or "released"}) as host:
                assert host.client is not None
                with host.client:
                    blocked = [jobs.start(host.client.call, "test.block", {}) for _ in range(8)]
                    queued = jobs.start(host.client.call, "test.echo", {"index": 9})
                    self.assertTrue(queued.cancel())
                    self.assertTrue(queued.done())
                    release.set()
                    blocker.set()
                    self.assertTrue(jobs.wait_all())
                    for job in blocked:
                        job.result()
                    with self.assertRaises(AgentError) as caught:
                        queued.result()
                    self.assertEqual(caught.exception.kind, "canceled")
        finally:
            blocker.set()
            release.set()

    def test_rejects_a_non_callable(self) -> None:
        with self.assertRaises(AgentError) as caught:
            jobs.start("not a callable")
        self.assertEqual(caught.exception.kind, "invalid_argument")


if __name__ == "__main__":
    unittest.main()
