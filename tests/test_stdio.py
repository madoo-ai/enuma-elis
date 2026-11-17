"""End-to-end stdio transport test.

The child is a real Python process using ``AGENT_BRIDGE_TRANSPORT=stdio``, the
same path the fork adapter uses.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHILD = r"""
import contextlib
import json
import os
import sys

import agent
from agent import fs


def Run(ctx, a):
    page = fs.read("README.md", limit=5)
    return {"text": page.text}


with agent.Client() as client:
    with contextlib.redirect_stdout(sys.stderr):
        value = Run(None, client)
os.write(1, (json.dumps({"type": "final", "ok": True, "value": agent.to_json(value)}) + "\n").encode())
os._exit(0)
"""


class StdioTransportTest(unittest.TestCase):
    def test_round_trip(self) -> None:
        env = {
            **os.environ,
            "AGENT_BRIDGE_TRANSPORT": "stdio",
            "AGENT_BRIDGE_FD": "1",
            "PYTHONPATH": str(ROOT),
        }
        proc = subprocess.Popen(
            [sys.executable, "-c", CHILD],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        assert proc.stdin is not None and proc.stdout is not None

        def send(message: dict) -> None:
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        try:
            hello = json.loads(proc.stdout.readline())
            self.assertEqual(hello["type"], "hello")
            send(
                {
                    "type": "hello",
                    "protocol": 1,
                    "tools": ["fs.read"],
                    "limits": {"calls": 10, "concurrency": 2},
                }
            )

            call = json.loads(proc.stdout.readline())
            self.assertEqual(call["type"], "call")
            self.assertEqual(call["tool"], "fs.read")
            send(
                {
                    "type": "result",
                    "id": call["id"],
                    "ok": True,
                    "output": {
                        "kind": "file",
                        "path": "README.md",
                        "text": "hello from stdio\n",
                        "lines": 1,
                        "truncated": False,
                    },
                }
            )

            final = json.loads(proc.stdout.readline())
            self.assertEqual(final["type"], "final")
            self.assertTrue(final["ok"])
            self.assertEqual(final["value"], {"text": "hello from stdio\n"})

            code = proc.wait(timeout=5)
            self.assertEqual(code, 0)
        finally:
            proc.kill()
            proc.wait(timeout=5)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()


if __name__ == "__main__":
    unittest.main()
