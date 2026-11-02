"""Search UI scope — dataset catalog vs business documents."""

from __future__ import annotations

import os
from typing import Literal

SearchScope = Literal["datasets", "docs", "both"]


def search_tab_scope() -> SearchScope:
    """TreePane Search タブのスコープ（``OPENSEARCH_SEARCH_SCOPE``）。"""
    raw = (os.environ.get("OPENSEARCH_SEARCH_SCOPE") or "datasets").strip().lower()
    if raw in ("docs", "both"):
        return raw  # type: ignore[return-value]
    return "datasets"


__all__ = ["SearchScope", "search_tab_scope"]
