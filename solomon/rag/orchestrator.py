"""Composite Retrieval Orchestrator — Knowledge Source を戦略に応じて実行。"""

from __future__ import annotations

from typing import Any, Optional

from solomon.rag.models import RetrievalBundle, RetrievalPlan, SourceHit
from solomon.semantic.store import search_datasets
from solomon.tools.neo4j_query import (
    query_all_datasets,
    query_dataset_lineage,
    query_system_assets,
)
from solomon.tools.opensearch import (
    OpenSearchHybridSearchTool,
    OpenSearchKeywordSearchTool,
    OpenSearchVectorSearchTool,
)
from solomon.tools.text2sql import Text2SQLTool
from solomon.transport.config import get_opensearch_config
from solomon.transport.user_context import UserContext


def _append_hit(
    hits: list[SourceHit],
    *,
    source: str,
    kind: str,
    payload: dict[str, Any],
    score: float | None = None,
) -> None:
    hits.append(
        SourceHit(
            source=source,  # type: ignore[arg-type]
            kind=kind,
            score=score,
            payload=payload,
        )
    )


def _append_error(errors: list[dict[str, str]], source: str, message: str) -> None:
    errors.append({"source": source, "message": message})


def _run_neo4j(plan: RetrievalPlan, hits: list[SourceHit], errors: list[dict[str, str]]) -> None:
    hint = plan.entity_hint or plan.query
    if plan.entity_hint or "システム" in plan.query:
        result = query_system_assets(hint)
    elif plan.strategy == "COMPOSITE" and not plan.entity_hint:
        result = query_all_datasets(limit=15)
    else:
        result = query_dataset_lineage(hint)
    if result.get("status") == "ok":
        _append_hit(hits, source="neo4j", kind="graph", payload=result)
    else:
        _append_error(errors, "neo4j", result.get("message", "neo4j failed"))


def _run_opensearch_keyword(
    query: str, hits: list[SourceHit], errors: list[dict[str, str]], top_k: int = 5
) -> None:
    tool = OpenSearchKeywordSearchTool()
    result = tool.run(user_ctx=None, query=query, top_k=top_k)
    if result.get("status") == "ok":
        for r in result.get("results", []):
            _append_hit(
                hits,
                source="opensearch",
                kind="keyword",
                payload=r,
                score=r.get("score"),
            )
    else:
        _append_error(errors, "opensearch", result.get("message", "keyword search failed"))


def _run_opensearch_hybrid(
    query: str, hits: list[SourceHit], errors: list[dict[str, str]], top_k: int = 5
) -> None:
    tool = OpenSearchHybridSearchTool()
    result = tool.run(user_ctx=None, query=query, top_k=top_k)
    if result.get("status") == "ok":
        for r in result.get("results", []):
            _append_hit(
                hits,
                source="opensearch",
                kind="hybrid",
                payload=r,
                score=r.get("score"),
            )
    else:
        _append_error(errors, "opensearch", result.get("message", "hybrid search failed"))


def _run_opensearch_vector(
    query: str, hits: list[SourceHit], errors: list[dict[str, str]], top_k: int = 5
) -> None:
    tool = OpenSearchVectorSearchTool()
    result = tool.run(user_ctx=None, query=query, top_k=top_k)
    if result.get("status") == "ok":
        for r in result.get("results", []):
            _append_hit(
                hits,
                source="opensearch",
                kind="vector",
                payload=r,
                score=r.get("score"),
            )
    else:
        _append_error(errors, "opensearch", result.get("message", "vector search failed"))


def _run_ossie_fallback(query: str, hits: list[SourceHit], top_k: int = 5) -> None:
    for r in search_datasets(query, top_k=top_k):
        _append_hit(
            hits,
            source="ossie",
            kind="tfidf",
            payload=r,
            score=r.get("score"),
        )


def _run_sql(
    plan: RetrievalPlan,
    user_ctx: Optional[UserContext],
    hits: list[SourceHit],
    errors: list[dict[str, str]],
) -> None:
    tool = Text2SQLTool()
    result = tool.run(
        user_ctx=user_ctx,
        question=plan.query,
        fq_table_hint=plan.fq_table_hint,
    )
    if result.get("status") == "ok":
        _append_hit(hits, source="lakehouse", kind="sql", payload=result)
    else:
        _append_error(errors, "lakehouse", result.get("message", "text2sql failed"))


def execute_retrieval(
    plan: RetrievalPlan,
    *,
    user_ctx: Optional[UserContext] = None,
) -> RetrievalBundle:
    """RetrievalStrategy に応じて Knowledge Source を実行する。"""
    hits: list[SourceHit] = []
    errors: list[dict[str, str]] = []
    strategy = plan.strategy
    query = plan.query
    has_opensearch = get_opensearch_config() is not None

    if strategy == "GRAPH_QUERY":
        _run_neo4j(plan, hits, errors)

    elif strategy == "SQL_ANALYTICS":
        _run_sql(plan, user_ctx, hits, errors)

    elif strategy == "KEYWORD":
        if has_opensearch:
            _run_opensearch_keyword(query, hits, errors)
        else:
            _run_ossie_fallback(query, hits)

    elif strategy == "HYBRID":
        if has_opensearch:
            _run_opensearch_hybrid(query, hits, errors)
        else:
            _run_ossie_fallback(query, hits)

    elif strategy == "COMPOSITE":
        _run_neo4j(plan, hits, errors)
        if has_opensearch:
            _run_opensearch_hybrid(query, hits, errors)
        else:
            _run_ossie_fallback(query, hits)
        _run_sql(plan, user_ctx, hits, errors)

    return RetrievalBundle(plan=plan, hits=hits, errors=errors)


__all__ = ["execute_retrieval"]
