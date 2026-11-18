import contextlib
import json
import os
import sys

import agent


def main():
    os.makedirs(os.environ.get("HOME", "/tmp/home"), exist_ok=True)
    try:
        with agent.Client() as client:
            from program import Run

            with contextlib.redirect_stdout(sys.stderr):
                value = Run(None, client)
        envelope = {"type": "final", "ok": True, "value": agent.to_json(value)}
    except BaseException as error:
        envelope = {"type": "final", "ok": False, "error": agent.to_error(error)}
    os.write(1, (json.dumps(envelope) + "\n").encode())
    os._exit(0)


main()
