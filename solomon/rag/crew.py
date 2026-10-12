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
        from solomon.graph.manufacturing.trace_qa import (
            try_answer_manufacturing_part_prompt,
            try_answer_manufacturing_trace_documents_prompt,
            try_answer_manufacturing_ingest_ledger_prompt,
            try_answer_manufacturing_trace_graph_prompt,
            try_answer_manufacturing_trace_prompt,
            try_answer_vb_machine_prompt,
            try_answer_vb_path_prompt,
        )

        ingest_ledger_answer = try_answer_manufacturing_ingest_ledger_prompt(
            prompt, user_ctx=user_ctx
        )
        if ingest_ledger_answer is not None:
            _logger.info(
                "knowledge_rag.ingest_ledger",
                user=user_ctx.user_name,
                trace_id=ingest_ledger_answer.plan.entity_hint,
            )
            return ok_result(ingest_ledger_answer)

        trace_graph_answer = try_answer_manufacturing_trace_graph_prompt(
            prompt, user_ctx=user_ctx
        )
        if trace_graph_answer is not None:
            _logger.info(
                "knowledge_rag.manufacturing_trace_graph",
                user=user_ctx.user_name,
                trace_id=trace_graph_answer.plan.entity_hint,
            )
            return ok_result(trace_graph_answer)

        trace_docs_answer = try_answer_manufacturing_trace_documents_prompt(
            prompt, user_ctx=user_ctx
        )
        if trace_docs_answer is not None:
            _logger.info(
                "knowledge_rag.manufacturing_trace_docs",
                user=user_ctx.user_name,
                trace_id=trace_docs_answer.plan.entity_hint,
            )
            return ok_result(trace_docs_answer)

        trace_answer = try_answer_manufacturing_trace_prompt(prompt, user_ctx=user_ctx)
        if trace_answer is not None:
            _logger.info(
                "knowledge_rag.manufacturing_trace",
                user=user_ctx.user_name,
                trace_id=trace_answer.plan.entity_hint,
            )
            return ok_result(trace_answer)

        part_answer = try_answer_manufacturing_part_prompt(prompt, user_ctx=user_ctx)
        if part_answer is not None:
            _logger.info(
                "knowledge_rag.manufacturing_part",
                user=user_ctx.user_name,
                part_no=part_answer.plan.entity_hint,
            )
            return ok_result(part_answer)

        vb_path_answer = try_answer_vb_path_prompt(prompt, user_ctx=user_ctx)
        if vb_path_answer is not None:
            _logger.info(
                "knowledge_rag.vb_path",
                user=user_ctx.user_name,
                terms=vb_path_answer.plan.entity_hint,
            )
            return ok_result(vb_path_answer)

        vb_machine_answer = try_answer_vb_machine_prompt(prompt, user_ctx=user_ctx)
        if vb_machine_answer is not None:
            _logger.info(
                "knowledge_rag.vb_machine",
                user=user_ctx.user_name,
                vb_id=vb_machine_answer.plan.entity_hint,
            )
            return ok_result(vb_machine_answer)

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
