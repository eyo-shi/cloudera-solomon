"""Knowledge RAG の有効ソース (table / graph / search) 解決。"""

from __future__ import annotations

from typing import Literal, Optional

RagSource = Literal["table", "graph", "search"]

RAG_SOURCES_ALL: tuple[RagSource, ...] = ("table", "graph", "search")

SOURCE_TO_TOOL: dict[RagSource, str] = {
    "table": "sql_query",
    "graph": "graph_query",
    "search": "doc_search",
}

SOURCE_LABEL_JA: dict[RagSource, str] = {
    "table": "テーブル",
    "graph": "Graph",
    "search": "Search",
}


def resolve_rag_sources(
    request_sources: Optional[list[str]],
    *,
    default: frozenset[str],
) -> tuple[frozenset[str], list[str]]:
    """有効ソース集合と無効ソース名リスト（表示順）を返す。"""
    if request_sources is not None:
        enabled = frozenset(request_sources)
    else:
        enabled = default
    disabled = [s for s in RAG_SOURCES_ALL if s not in enabled]
    return enabled, disabled


def format_sources_status_message(enabled: frozenset[str]) -> str:
    """SSE 用: ``ソース構成: table+graph（search 無効）``。"""
    parts = [s for s in RAG_SOURCES_ALL if s in enabled]
    disabled = [s for s in RAG_SOURCES_ALL if s not in enabled]
    core = "+".join(parts) if parts else "なし"
    if disabled:
        return f"ソース構成: {core}（{'+'.join(disabled)} 無効）"
    return f"ソース構成: {core}"


def preset_to_sources(preset: str) -> list[RagSource]:
    mapping: dict[str, list[RagSource]] = {
        "table": ["table"],
        "table_graph": ["table", "graph"],
        "table_search": ["table", "search"],
        "all": list(RAG_SOURCES_ALL),
    }
    return mapping.get(preset, list(RAG_SOURCES_ALL))


def preset_label_ja(preset: str) -> str:
    labels: dict[str, str] = {
        "table": "テーブルのみ",
        "table_graph": "テーブル＋Graph",
        "table_search": "テーブル＋Search",
        "all": "全部",
    }
    return labels.get(preset, preset)
