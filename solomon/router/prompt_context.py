"""Router LLM 分類用の Ossie / ソースカタログ要約 (TTL キャッシュ)。"""

from __future__ import annotations

import time
from typing import Any

from solomon.semantic.context import SemanticContext, get_semantic_context
from solomon.semantic.source_catalog import SourceCatalog, build_source_catalog

_TTL_SEC = 300.0
_cache_at: float = 0.0
_cache_pack: dict[str, str] | None = None

_MAX_TOTAL = 4000


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _escape_crew_braces(text: str) -> str:
    """CrewAI inputs 展開で `{` が壊れないようリテラル波括弧をエスケープ。"""
    return text.replace("{", "{{").replace("}", "}}")


def _render_domain_context(ctx: SemanticContext, limit: int) -> str:
    lines: list[str] = []
    for model in ctx.models:
        if model.description:
            lines.append(f"- **{model.name}**: {model.description[:200]}")
        from solomon.semantic.context import _instructions  # noqa: PLC0415

        instr = _instructions(model.ai_context)
        if instr:
            lines.append(f"  - {instr[:300]}")
    for entry in ctx.glossary[:25]:
        term = entry.get("term") or ""
        desc = entry.get("description") or ""
        if term:
            lines.append(f"- 用語 **{term}**: {desc[:120]}")
    return _truncate("\n".join(lines) or "(no business context)", limit)


def _render_source_catalog(ctx: SemanticContext, catalog: SourceCatalog, limit: int) -> str:
    lines: list[str] = ["### テーブル"]
    for row in catalog.tables[:40]:
        fq = row.get("fq_name") or ""
        desc = ""
        for ds in ctx.datasets:
            if ds.get("fq_name") == fq:
                desc = str(ds.get("description") or "")[:100]
                break
        lines.append(f"- `{fq}`: {desc}" if desc else f"- `{fq}`")
    lines.append("### グラフ")
    for g in ctx.graph_definitions[:15]:
        v = g.get("vertex") or {}
        label = v.get("label")
        if label:
            lines.append(
                f"- 頂点 `{label}`: {(v.get('description') or '')[:80]}"
            )
        for e in (g.get("edges") or [])[:5]:
            lines.append(
                f"  - `{e.get('label')}` {e.get('from_label')} -> {e.get('to_label')}"
            )
    lines.append("### 文書種別")
    for doc in catalog.search[:10]:
        for dt in doc.get("doc_types") or []:
            lines.append(
                f"- `{dt.get('id')}` {dt.get('label', '')}: "
                f"{(dt.get('description') or '')[:80]}"
            )
    if catalog.warnings:
        lines.append("### 接続警告")
        for w in catalog.warnings[:3]:
            lines.append(f"- {w[:120]}")
    return _truncate("\n".join(lines), limit)


def _render_routing_examples(ctx: SemanticContext, limit: int) -> str:
    lines: list[str] = []
    for q in ctx.example_questions[:8]:
        q = (q or "").strip()
        if q:
            lines.append(f"- {q} -> KNOWLEDGE_RAG")
    for ex in ctx.graph_examples[:3]:
        q = str(ex.get("question") or "").strip()
        if q:
            lines.append(f"- {q} -> KNOWLEDGE_RAG")
    return _truncate("\n".join(lines) or "(no routing examples)", limit)


def build_router_prompt_pack(
    *,
    force: bool = False,
    max_total: int = _MAX_TOTAL,
) -> dict[str, str]:
    """``domain_context`` / ``source_catalog`` / ``routing_examples`` を返す。"""
    global _cache_at, _cache_pack
    now = time.monotonic()
    if not force and _cache_pack is not None and (now - _cache_at) < _TTL_SEC:
        return dict(_cache_pack)

    ctx = get_semantic_context(force=force)
    catalog = build_source_catalog(force=force)
    if not ctx.models:
        pack = {
            "domain_context": _escape_crew_braces("(semantic models not loaded)"),
            "source_catalog": _escape_crew_braces("(no source catalog)"),
            "routing_examples": _escape_crew_braces("(no examples)"),
        }
        _cache_at = now
        _cache_pack = pack
        return dict(pack)

    budget = max_total
    domain = _render_domain_context(ctx, min(1200, budget // 3))
    budget -= len(domain)
    catalog_text = _render_source_catalog(ctx, catalog, min(2000, max(800, budget // 2)))
    budget -= len(catalog_text)
    examples = _render_routing_examples(ctx, max(400, budget))

    pack = {
        "domain_context": _escape_crew_braces(domain),
        "source_catalog": _escape_crew_braces(catalog_text),
        "routing_examples": _escape_crew_braces(examples),
    }
    _cache_at = now
    _cache_pack = pack
    return dict(pack)


__all__ = ["build_router_prompt_pack"]
