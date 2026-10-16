"""Search UI scope — generic Solomon uses dataset catalog index only."""

from __future__ import annotations

from typing import Literal

SearchScope = Literal["datasets"]


def search_tab_scope() -> SearchScope:
    """TreePane Search タブの既定スコープ（外部パイプラインが投入済みの ``solomon-datasets``）。"""
    return "datasets"


__all__ = ["SearchScope", "search_tab_scope"]
