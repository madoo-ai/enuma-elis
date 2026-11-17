"""Network tools.

Public surface, generated from ``tool-manifest.json``::

    web.fetch(url, format="markdown", timeout=None) -> FetchResult
    web.search(query, num_results=None, livecrawl=None) -> SearchResult

Both go through the host so the call is permission-checked and truncated.

TODO: generate the typed implementations from the manifest.
"""

__all__: list[str] = []
