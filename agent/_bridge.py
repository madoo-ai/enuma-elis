"""fd 3 emitter.

The host reserves fd 3 for the call stream and fd 4 for the final envelope.
This module owns the write side and the lock shared by the SDK and the
``sitecustomize`` audit hook. The reader/multiplexer lands with ``Client``.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

_LOCK = threading.Lock()
_FD = int(os.environ.get("AGENT_BRIDGE_FD", "3"))


def emit(message: dict[str, Any]) -> None:
    """Write one JSON line to the bridge.

    Outside code mode (local tests, a plain ``python3 program.py``) there is no
    bridge fd; the write is ignored rather than crashing the program.
    """

    data = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
    with _LOCK:
        try:
            os.write(_FD, data)
        except OSError:
            pass
