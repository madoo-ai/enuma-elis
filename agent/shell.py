"""Process execution.

Public surface, generated from ``tool-manifest.json``::

    shell.run(command, workdir=None, timeout=None, check=False) -> Result

``Result`` carries ``exit``, ``stdout``, ``stderr``, ``output``,
``truncated``, and ``output_path``. The host kills the process group on
timeout or abort.

TODO: generate the typed implementation from the manifest.
"""

__all__: list[str] = []
