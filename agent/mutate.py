"""Filesystem mutation tools.

Public surface, generated from ``tool-manifest.json``::

    mutate.edit(path, old, new, replace_all=False) -> EditResult
    mutate.write(path, content) -> WriteResult
    mutate.patch(text) -> PatchResult

Every call uses the fork's ``edit`` permission and returns the diff it applied.

TODO: generate the typed implementations from the manifest.
"""

__all__: list[str] = []
