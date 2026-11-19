"""Generated SDK reference, for programs that would otherwise ``dir()`` the package."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

from ._program import MODULES


def _enabled(module: str) -> bool:
    from . import _ACTIVE_STACK

    if not _ACTIVE_STACK:
        return True
    client = _ACTIVE_STACK[-1]
    if not client.tools:
        return True
    return any(tool.startswith(f"{module}.") for tool in client.tools)


def _line(prefix: str, fn: Any) -> str:
    try:
        signature = str(inspect.signature(fn)).replace("'", "")
    except (TypeError, ValueError):
        signature = "(...)"
    doc = (inspect.getdoc(fn) or "").split("\n")[0]
    return f"{prefix}{signature}" + (f"  # {doc}" if doc else "")


def _members(module: Any) -> list[str]:
    lines = []
    for name in getattr(module, "__all__", []):
        item = getattr(module, name)
        if inspect.isfunction(item):
            lines.append(_line(f"{module.__name__.split('.')[-1]}.{name}", item))
        elif inspect.isclass(item):
            prefix = {"Page": "page", "ScratchPage": "scratch", "Element": "element"}.get(name, name)
            # Only list a subclass's own additions, so help stays compact.
            methods = dir(item) if name == "Page" else item.__dict__
            for method in sorted(methods):
                fn = getattr(item, method)
                if not method.startswith("_") and callable(fn):
                    lines.append(_line(f"{prefix}.{method}", fn))
        elif not inspect.ismodule(item) and not inspect.isclass(item) and not name.startswith("_"):
            for method in sorted(dir(item)):
                fn = getattr(item, method)
                if not method.startswith("_") and callable(fn):
                    lines.append(_line(f"{module.__name__.split('.')[-1]}.{name}.{method}", fn))
    return lines


def reference(module: str | None = None) -> str:
    names = [module] if module else [name for name in MODULES if name != "jobs" and _enabled(name)]
    lines: list[str] = []
    for name in names:
        if name not in MODULES:
            return f"unknown module {name!r}; modules: {', '.join(MODULES)}"
        lines.extend(_members(importlib.import_module(f"agent.{name}")))
    if module is None:
        lines.append("agent.jobs.start(fn, *args, **kwargs) -> Job  # run a call in the background; job.result()")
    return "\n".join(lines)
