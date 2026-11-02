"""Ossie / ソースカタログ由来の Router ヒューリスティック (業種語彙なし)。"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Any

from solomon.semantic.context import SemanticContext, get_semantic_context
from solomon.semantic.search import tokenize
from solomon.semantic.source_catalog import SourceCatalog, build_source_catalog

_GENERIC_INVESTIGATION = re.compile(
    r"[?？]|"
    r"なぜ|どの|どれ|いつ|何件|何人|いくつ|"
    r"一覧|リスト|調べ|確認|特定|教えて|見つけ|"
    r"\bhow many\b|\bhow much\b|\bwhich\b|\bwhen\b|\bwhy\b|\blist\b|\bfind\b|\bsearch\b",
    re.IGNORECASE,
)

_FQ_TABLE_RE = re.compile(
    r"\b([a-zA-Z0-9_\-]+)\.([a-zA-Z0-9_\-]+)\.([a-zA-Z0-9_\-]+)\b"
)


def _knowledge_threshold() -> float:
    raw = (os.environ.get("SOLOMON_ROUTER_KNOWLEDGE_THRESHOLD") or "0.35").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.35


def _cosine_similarity(a: str, b: str) -> float:
    ta = tokenize(a)
    tb = tokenize(b)
    if not ta or not tb:
        return 0.0
    ca, cb = Counter(ta), Counter(tb)
    keys = set(ca) | set(cb)
    dot = sum(ca.get(k, 0) * cb.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _collect_vocabulary(
    ctx: SemanticContext,
    catalog: SourceCatalog,
) -> list[tuple[str, str]]:
    """(term, source_kind) — source_kind: table|graph|search|glossary|field."""
    out: list[tuple[str, str]] = []

    def add(term: str, kind: str, *, min_len: int = 2) -> None:
        t = (term or "").strip()
        if len(t) < min_len:
            return
        out.append((t, kind))

    for entry in ctx.glossary:
        add(str(entry.get("term") or ""), "glossary")
        for syn in entry.get("synonyms") or []:
            add(str(syn), "glossary")

    for ds in ctx.datasets:
        add(ds.get("name") or "", "table")
        add(ds.get("fq_name") or "", "table", min_len=3)

    for model in ctx.models:
        for dataset in model.datasets:
            add(dataset.name, "table")
            for field in dataset.fields:
                add(field.name, "field")
                if field.label:
                    add(field.label, "field")
                ctx_ai = field.ai_context
                if ctx_ai and not isinstance(ctx_ai, str):
                    for syn in ctx_ai.synonyms or []:
                        add(syn, "field")
            ds_ai = dataset.ai_context
            if ds_ai and not isinstance(ds_ai, str):
                for syn in ds_ai.synonyms or []:
                    add(syn, "table")

    for g in ctx.graph_definitions:
        v = g.get("vertex") or {}
        add(str(v.get("label") or ""), "graph")
        for e in g.get("edges") or []:
            add(str(e.get("label") or ""), "graph")
            add(str(e.get("from_label") or ""), "graph")
            add(str(e.get("to_label") or ""), "graph")

    for doc in ctx.document_indexes:
        for dt in doc.get("doc_types") or []:
            add(str(dt.get("label") or ""), "search")
            add(str(dt.get("id") or ""), "search")

    for row in catalog.tables:
        fq = str(row.get("fq_name") or "")
        if fq.count(".") >= 2:
            parts = fq.split(".")
            add(parts[-1], "table")

    return out


def _term_in_prompt(term: str, prompt: str, prompt_lower: str) -> bool:
    if not term:
        return False
    if re.search(r"[a-zA-Z0-9_]", term):
        if term.lower() in prompt_lower:
            return True
        return term in prompt
    return term in prompt


def knowledge_relevance(
    prompt: str,
    context: SemanticContext,
    catalog: SourceCatalog,
) -> tuple[float, list[str]]:
    """0–1 付近のスコアと、根拠ラベルのリスト。"""
    if not context.models:
        return 0.0, []

    text = prompt.strip()
    if not text:
        return 0.0, []

    reasons: list[str] = []
    score = 0.0
    lower = text.lower()

    if _GENERIC_INVESTIGATION.search(text):
        score += 0.12
        reasons.append("generic_investigation_phrase")

    vocab = _collect_vocabulary(context, catalog)
    kinds_hit: set[str] = set()
    term_hits = 0
    for term, kind in vocab:
        if _term_in_prompt(term, text, lower):
            term_hits += 1
            kinds_hit.add(kind)
            if term_hits <= 5:
                reasons.append(f"term:{term[:40]}")

    if term_hits:
        score += min(0.55, 0.08 * term_hits)
        reasons.append(f"vocabulary_hits={term_hits}")
        if _GENERIC_INVESTIGATION.search(text):
            score = max(score, _knowledge_threshold() + 0.02)
            reasons.append("vocabulary_plus_investigation_phrase")

    examples: list[str] = list(context.example_questions)
    for ex in context.graph_examples:
        q = ex.get("question")
        if q:
            examples.append(str(q))
    for model in context.models:
        for ds in model.datasets:
            ai = ds.ai_context
            if ai and not isinstance(ai, str):
                examples.extend(ai.examples or [])

    best_sim = 0.0
    best_ex = ""
    for ex in examples:
        sim = _cosine_similarity(text, ex)
        if sim > best_sim:
            best_sim = sim
            best_ex = ex
    if best_sim >= 0.25:
        score += min(0.45, best_sim * 0.6)
        reasons.append(f"example_similarity={best_sim:.2f}")
        if best_ex:
            reasons.append(f"nearest_example:{best_ex[:60]}")

    if len(kinds_hit) >= 2:
        score += 0.08
        reasons.append(f"multi_source_kinds={sorted(kinds_hit)}")

    return min(1.0, score), reasons


def matched_source_kinds(
    prompt: str,
    context: SemanticContext,
    catalog: SourceCatalog,
) -> set[str]:
    """語彙一致から table / graph / search のどれが触れられているか。"""
    if not context.models:
        return set()
    lower = prompt.lower()
    kinds: set[str] = set()
    for term, kind in _collect_vocabulary(context, catalog):
        if not _term_in_prompt(term, prompt, lower):
            continue
        if kind in ("table", "field", "glossary"):
            kinds.add("table")
        elif kind == "graph":
            kinds.add("graph")
        elif kind == "search":
            kinds.add("search")
    return kinds


def extract_fq_table_name(prompt: str) -> str | None:
    m = _FQ_TABLE_RE.search(prompt)
    if m:
        return m.group(0)
    return None


def load_router_semantic_bundle(
    *,
    force: bool = False,
) -> tuple[SemanticContext, SourceCatalog]:
    ctx = get_semantic_context(force=force)
    catalog = build_source_catalog(force=force)
    return ctx, catalog


__all__ = [
    "knowledge_relevance",
    "matched_source_kinds",
    "extract_fq_table_name",
    "load_router_semantic_bundle",
    "_knowledge_threshold",
]
