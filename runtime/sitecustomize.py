"""Audit hook installed as ``lib/sitecustomize.py``.

Python imports ``sitecustomize`` at startup. The hook reports raw capability
use to the host on fd 3. It is measurement, not enforcement; the bwrap mounts
are the enforcement. ``ctypes`` can bypass it; the host's snapshot diff is the
backstop.
"""

from __future__ import annotations

import sys
from typing import Any

from agent import _bridge


def _hook(event: str, args: tuple[Any, ...]) -> None:
    try:
        if event == "open":
            path, mode, _flags = args
            if mode and any(flag in mode for flag in "wax+"):
                _bridge.emit(
                    {"type": "audit", "kind": "raw_open", "path": str(path), "mode": mode}
                )
        elif event in ("subprocess.Popen", "os.system"):
            _bridge.emit({"type": "audit", "kind": "raw_exec", "argv": repr(args)})
        elif event == "socket.connect":
            _bridge.emit({"type": "audit", "kind": "raw_net", "address": repr(args)})
    except Exception:
        # The hook must never break the program.
        pass


sys.addaudithook(_hook)
