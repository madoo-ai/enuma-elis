"""Python code mode SDK for the manica-dei/opencode fork.

Model-written programs import narrow modules::

    from agent import fs, mutate, shell, web, state

The import is the capability. The SDK speaks newline-delimited JSON on fd 3
and writes its final envelope on fd 4. See ``spec/protocol.md``.

This package is a skeleton; the full bridge and generated modules land with
the plan in ``python-code-mode-plan.md``.
"""

from __future__ import annotations

from ._errors import AgentError

__version__ = "0.0.0"


class Client:
    """Bridge client.

    The real client owns the fd 3 reader, multiplexes calls by id, and maps
    tool failures to :class:`AgentError`. The skeleton only fixes the shape so
    the harness and tests can import it.
    """

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def call(self, tool: str, input: dict[str, object]) -> object:
        raise NotImplementedError("agent.Client.call is not implemented yet")


__all__ = ["AgentError", "Client", "__version__"]
