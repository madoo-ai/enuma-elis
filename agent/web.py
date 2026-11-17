"""Network tools: fetch and search."""

from __future__ import annotations

from typing import Any

from . import current_client
from ._types import FetchResult, SearchResult, parse_fetch, parse_search


def fetch(url: str, format: str = "markdown", timeout: int | None = None) -> FetchResult:
    """Fetch one http(s) URL through the host."""

    payload: dict[str, Any] = {"url": url, "format": format}
    if timeout is not None:
        payload["timeout"] = timeout
    return parse_fetch(current_client().call("web.fetch", payload))


def search(
    query: str,
    num_results: int | None = None,
    livecrawl: str | None = None,
    search_type: str | None = None,
    context_max_characters: int | None = None,
) -> SearchResult:
    """Search the web through the host's configured provider."""

    payload: dict[str, Any] = {"query": query}
    if num_results is not None:
        payload["num_results"] = num_results
    if livecrawl is not None:
        payload["livecrawl"] = livecrawl
    if search_type is not None:
        payload["type"] = search_type
    if context_max_characters is not None:
        payload["context_max_characters"] = context_max_characters
    return parse_search(current_client().call("web.search", payload))


__all__ = ["fetch", "search"]
