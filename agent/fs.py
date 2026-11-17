"""Read-only filesystem tools.

Public surface, generated from ``tool-manifest.json``::

    fs.read(path, offset=None, limit=None) -> Text | Image | Directory
    fs.glob(pattern, path=None, limit=None) -> list[FileEntry]
    fs.grep(pattern, path=None, include=None, limit=None) -> list[Match]
    fs.list(path, offset=None, limit=None) -> Directory   # helper over read

TODO: generate the typed implementations and permissions from the manifest.
"""

__all__: list[str] = []
