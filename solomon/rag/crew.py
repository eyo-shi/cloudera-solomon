"""Agentic RAG kickoff — Knowledge Router + Composite Retrieval + Synthesis。"""

from __future__ import annotations

from typing import Any, Optional

from solomon.rag.classifier import classify_retrieval
from solomon.rag.models import KnowledgeRagResult
from solomon.rag.orchestrator import execute_retrieval
from solomon.rag.synthesizer import synthesize_answer
from solomon.transport.logging import get_logger
from solomon.transport.user_context import (
    UserContext,
    reset_user_context,
    set_user_context,
)

_logger = get_logger(__name__)


def kickoff_knowledge_rag(
    *,
    user_ctx: UserContext,
    prompt: str,
    llm_strong: Optional[Any] = None,
) -> dict[str, Any]:
    """Agentic RAG パイプラインを 1 回実行する。

    1. Knowledge Router — 質問を RetrievalStrategy に分類
    2. Composite Retrieval — Neo4j / OpenSearch / Lakehouse を並列実行
    3. Synthesizer — 検索結果を Markdown 回答に統合

    CrewAI Agent は将来拡張用。コアロジックは Python オーケストレータで決定論的に動く。
    """
    token = set_user_context(user_ctx)
    try:
        plan = classify_retrieval(prompt)
        _logger.info(
            "knowledge_rag.start",
            strategy=plan.strategy,
            user=user_ctx.user_name,
        )
        bundle = execute_retrieval(plan, user_ctx=user_ctx)
        result = synthesize_answer(bundle)
    finally:
        reset_user_context(token)

    return ok_result(result)


def ok_result(result: KnowledgeRagResult) -> dict[str, Any]:
    """API / Tool 向け dict に変換。"""
    return {
        "status": "ok",
        "strategy": result.plan.strategy,
        "confidence": result.plan.confidence,
        "answer_markdown": result.answer_markdown,
        "sql_executed": result.sql_executed,
        "hit_count": len(result.bundle.hits),
        "errors": result.bundle.errors,
        "hits": [h.model_dump() for h in result.bundle.hits],
    }


__all__ = ["kickoff_knowledge_rag", "ok_result"]
