"""Load and run a model-written program.

Models write programs that are close to correct. The loader forgives the
mistakes seen in practice and keeps the real error otherwise:

* a script with no ``Run`` is wrapped in ``Run(ctx, a)``, and a trailing bare
  expression becomes its return value;
* the SDK modules are already in scope, so a forgotten import still works;
* ``import fs`` or ``from agents import tasks`` resolve to ``agent.fs`` and
  ``agent.agents`` when nothing else has that name.
"""

from __future__ import annotations

import ast
import importlib
import importlib.abc
import importlib.util
import linecache
import os
import sys
import types
from typing import Any

MODULES = ("fs", "mutate", "shell", "web", "state", "agents", "browser", "jobs")


class _AliasFinder(importlib.abc.MetaPathFinder):
    """Resolve ``import fs`` to ``agent.fs`` after every other finder failed."""

    def find_spec(self, name: str, path: Any = None, target: Any = None):
        if name not in MODULES:
            return None
        module = importlib.import_module(f"agent.{name}")
        return importlib.util.spec_from_loader(name, _AliasLoader(module))


class _AliasLoader(importlib.abc.Loader):
    def __init__(self, module: types.ModuleType) -> None:
        self._module = module

    def create_module(self, spec: Any) -> types.ModuleType:
        return self._module

    def exec_module(self, module: types.ModuleType) -> None:
        return None


def install_aliases() -> None:
    if not any(isinstance(finder, _AliasFinder) for finder in sys.meta_path):
        sys.meta_path.append(_AliasFinder())


def _is_print(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    )


def wrap_script(tree: ast.Module) -> ast.Module:
    """Move a script's body into ``def Run(ctx, a)``. Imports stay at module level."""

    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    rest = [node for node in tree.body if node not in imports]
    if rest and isinstance(rest[-1], ast.Expr):
        last = rest[-1]
        constant = isinstance(last.value, ast.Constant)
        if not constant and not _is_print(last.value):
            rest[-1] = ast.copy_location(ast.Return(value=last.value), last)
    run = ast.FunctionDef(
        name="Run",
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="ctx"), ast.arg(arg="a")],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=rest or [ast.Pass()],
        decorator_list=[],
        returns=None,
        type_params=[],
    )
    wrapped = ast.Module(body=[*imports, run], type_ignores=[])
    return ast.fix_missing_locations(wrapped)


def _defines_run(tree: ast.Module) -> bool:
    return any(isinstance(node, ast.FunctionDef) and node.name == "Run" for node in tree.body)


def run_program(path: str, client: Any) -> Any:
    """Execute the program at ``path`` and return what its ``Run`` returns."""

    install_aliases()
    path = os.path.abspath(path)
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    linecache.cache[path] = (len(source), None, source.splitlines(True), path)

    tree = ast.parse(source, path)
    wrapped = not _defines_run(tree)
    if wrapped:
        tree = wrap_script(tree)
        print("note: no Run(ctx, a) was defined, so the program body ran as Run.", file=sys.stderr)

    import agent

    namespace: dict[str, Any] = {
        "__name__": "program",
        "__file__": path,
        "agent": agent,
        "AgentError": agent.AgentError,
    }
    for name in MODULES:
        namespace[name] = importlib.import_module(f"agent.{name}")
    exec(compile(tree, path, "exec"), namespace)
    return namespace["Run"](None, client)
