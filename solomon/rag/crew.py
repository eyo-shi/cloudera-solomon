"""Agentic RAG kickoff — heuristic 3 段 or ReAct ツールエージェント。"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

from solomon.rag.classifier import classify_retrieval
from solomon.rag.models import KnowledgeRagResult
from solomon.rag.orchestrator import execute_retrieval
from solomon.rag.sources import resolve_rag_sources
from solomon.rag.synthesizer import synthesize_answer
from solomon.transport.config import get_llm_agent_config, get_rag_default_sources
from solomon.transport.logging import get_logger
from solomon.transport.user_context import (
    UserContext,
    reset_user_context,
    set_user_context,
)

_logger = get_logger(__name__)

EventCallback = Callable[[dict[str, Any]], None]


def _rag_engine() -> str:
    return (os.environ.get("SOLOMON_RAG_ENGINE") or "agent").strip().lower()


def _run_heuristic(
    user_ctx: UserContext,
    prompt: str,
    *,
    enabled_sources: frozenset[str],
) -> KnowledgeRagResult:
    plan = classify_retrieval(prompt)
    _logger.info(
        "knowledge_rag.heuristic.start",
        strategy=plan.strategy,
        user=user_ctx.user_name,
        sources=sorted(enabled_sources),
    )
    bundle = execute_retrieval(plan, user_ctx=user_ctx, enabled_sources=enabled_sources)
    return synthesize_answer(bundle)


def _run_agent(
    user_ctx: UserContext,
    prompt: str,
    on_event: EventCallback | None,
    *,
    enabled_sources: frozenset[str],
    disabled_sources: list[str],
) -> KnowledgeRagResult:
    from solomon.rag.agent import run_knowledge_agent

    _logger.info(
        "knowledge_rag.agent.start",
        user=user_ctx.user_name,
        sources=sorted(enabled_sources),
    )
    return run_knowledge_agent(
        prompt,
        user_ctx=user_ctx,
        on_event=on_event,
        enabled_sources=enabled_sources,
        disabled_sources=disabled_sources,
    )


def kickoff_knowledge_rag(
    *,
    user_ctx: UserContext,
    prompt: str,
    llm_strong: Optional[Any] = None,
    on_event: EventCallback | None = None,
    sources: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Knowledge RAG を 1 回実行する。

    ``SOLOMON_RAG_ENGINE=agent``（既定）では ReAct ツールエージェント。
    ``heuristic`` では従来の classify → retrieve → synthesize。
    agent で ``rag_agent`` LLM が未設定の場合は heuristic にフォールバック。
    """
    _ = llm_strong
    enabled, disabled = resolve_rag_sources(
        sources, default=get_rag_default_sources()
    )
    engine = _rag_engine()
    token = set_user_context(user_ctx)
    try:
        use_agent = engine == "agent" and get_llm_agent_config("rag_agent") is not None
        if engine == "agent" and not use_agent:
            _logger.info("knowledge_rag.agent_fallback_heuristic")
            engine = "heuristic"

        if use_agent:
            result = _run_agent(
                user_ctx,
                prompt,
                on_event,
                enabled_sources=enabled,
                disabled_sources=disabled,
            )
        else:
            result = _run_heuristic(
                user_ctx, prompt, enabled_sources=enabled
            )
    finally:
        reset_user_context(token)

    return ok_result(
        result,
        engine=engine,
        sources=sorted(enabled),
        disabled_sources=disabled,
    )


def ok_result(
    result: KnowledgeRagResult,
    *,
    engine: str = "heuristic",
    sources: list[str] | None = None,
    disabled_sources: list[str] | None = None,
) -> dict[str, Any]:
    """API / Tool 向け dict に変換。"""
    src = sources if sources is not None else []
    disabled = (
        disabled_sources
        if disabled_sources is not None
        else list(result.bundle.disabled_sources)
    )
    return {
        "status": "ok",
        "engine": engine,
        "strategy": result.plan.strategy,
        "confidence": result.plan.confidence,
        "answer_markdown": result.answer_markdown,
        "sql_executed": result.sql_executed,
        "hit_count": len(result.bundle.hits),
        "errors": result.bundle.errors,
        "hits": [h.model_dump() for h in result.bundle.hits],
        "tool_calls": list(result.tool_calls),
        "steps": len(result.tool_calls),
        "sources": src,
        "disabled_sources": disabled,
    }


__all__ = ["kickoff_knowledge_rag", "ok_result"]
