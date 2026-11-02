"""LLM による doc_search クエリ言い換え（Ossie 手掛かりのみ、業種語固定なし）。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from functools import lru_cache
from typing import Any, Optional

from solomon.semantic.context import SemanticContext, get_semantic_context
from solomon.semantic.models import AIContext
from solomon.semantic.search import tokenize
from solomon.semantic.solomon_extension import extract_solomon_extensions
from solomon.semantic.store import load_models, semantic_generation
from solomon.transport.llm import try_json_completion
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

_GENERIC_EXPANSION_INSTRUCTIONS = (
    "文書検索のために、同じ事象を別の書き手が書いたときの言い方を挙げよ。"
    "口語・略称・擬音語、専門用語、症状と原因の両側の表現を含める。"
    "元の語を繰り返さない。固有の ID は表記ゆれを 1 つまで。"
)


def doc_search_expansion_enabled() -> bool:
    raw = (os.environ.get("SOLOMON_DOC_SEARCH_EXPANSION") or "on").strip().lower()
    return raw not in ("off", "false", "0", "no")


def doc_search_max_variants() -> int:
    raw = (os.environ.get("SOLOMON_DOC_SEARCH_MAX_VARIANTS") or "4").strip()
    try:
        return max(0, min(8, int(raw)))
    except ValueError:
        return 4


def _search_settings_from_context(ctx: SemanticContext) -> dict[str, Any]:
    merged: dict[str, Any] = {"use_synonyms": True}
    instructions: list[str] = []
    for model in ctx.models:
        ext = extract_solomon_extensions(model.custom_extensions)
        search = ext.get("search")
        if isinstance(search, dict):
            if search.get("expansion_instructions"):
                instructions.append(str(search["expansion_instructions"]))
            if "use_synonyms" in search:
                merged["use_synonyms"] = bool(search.get("use_synonyms"))
    if instructions:
        merged["expansion_instructions"] = "\n".join(instructions)
    return merged


def _ai_synonyms(ctx_obj: AIContext | str | None) -> list[str]:
    if ctx_obj is None or isinstance(ctx_obj, str):
        return []
    return list(ctx_obj.synonyms or [])


def _matching_synonym_hints(query: str, ctx: SemanticContext, *, limit: int = 20) -> list[str]:
    q_tokens = set(tokenize(query))
    if not q_tokens:
        return []
    hints: list[str] = []
    seen: set[str] = set()

    def add(term: str, syns: list[str]) -> None:
        term_toks = set(tokenize(term))
        if not (term_toks & q_tokens):
            return
        for syn in syns:
            s = syn.strip()
            if s and s not in seen:
                seen.add(s)
                hints.append(f"{term} -> {s}")

    for entry in ctx.glossary:
        term = str(entry.get("term") or "")
        syns = [str(x) for x in entry.get("synonyms") or []]
        add(term, syns)

    for model in load_models():
        for ds in model.datasets:
            add(ds.name, _ai_synonyms(ds.ai_context))
            for field in ds.fields:
                add(field.name, _ai_synonyms(field.ai_context))
                if field.label:
                    add(field.label, _ai_synonyms(field.ai_context))
        add(model.name, _ai_synonyms(model.ai_context))

    return hints[:limit]


def build_expansion_prompt(
    query: str,
    *,
    context: SemanticContext | None = None,
    max_variants: int = 4,
) -> str:
    ctx = context or get_semantic_context()
    settings = _search_settings_from_context(ctx)
    parts = [
        _GENERIC_EXPANSION_INSTRUCTIONS,
        f"\n元のクエリ: {query}",
        f"\n生成する言い換えの最大数: {max_variants}",
        '\nJSON のみ: {{"variants": ["...", "..."]}}',
    ]
    extra = settings.get("expansion_instructions")
    if extra:
        parts.insert(1, f"\n追加指示（この環境の文書の書き方）:\n{extra}")
    if settings.get("use_synonyms", True):
        hints = _matching_synonym_hints(query, ctx)
        if hints:
            parts.insert(
                -1,
                "\n参考になる既知の別名（機械置換せず、言い換え生成の手掛かりに使う）:\n"
                + "\n".join(f"- {h}" for h in hints),
            )
    return "\n".join(parts)


@lru_cache(maxsize=128)
def _expand_query_cached(
    query: str,
    model_generation: str,
    max_variants: int,
) -> tuple[str, ...]:
    _ = model_generation  # cache bust when semantic files change
    prompt = build_expansion_prompt(query, max_variants=max_variants)
    parsed = try_json_completion(
        prompt,
        agent_key="doc_query_expansion",
        role="light",
        temperature=0.3,
        max_tokens=512,
    )
    if not parsed or not isinstance(parsed.get("variants"), list):
        return ()
    out: list[str] = []
    q_norm = query.strip().lower()
    for item in parsed["variants"]:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text or text.lower() == q_norm:
            continue
        if text in out:
            continue
        out.append(text)
        if len(out) >= max_variants:
            break
    return tuple(out)


def expand_query(
    query: str,
    *,
    max_variants: int | None = None,
    context: SemanticContext | None = None,
) -> list[str]:
    """言い換えクエリ一覧（LLM 失敗時は空）。"""
    text = (query or "").strip()
    if not text:
        return []
    limit = max_variants if max_variants is not None else doc_search_max_variants()
    if limit <= 0:
        return []
    if context is not None:
        prompt = build_expansion_prompt(text, context=context, max_variants=limit)
        parsed = try_json_completion(
            prompt,
            agent_key="doc_query_expansion",
            role="light",
            temperature=0.3,
            max_tokens=512,
        )
        if not parsed or not isinstance(parsed.get("variants"), list):
            return []
        variants: list[str] = []
        q_norm = text.lower()
        for item in parsed["variants"]:
            if isinstance(item, str):
                v = item.strip()
                if v and v.lower() != q_norm and v not in variants:
                    variants.append(v)
            if len(variants) >= limit:
                break
        return variants
    return list(_expand_query_cached(text, semantic_generation(), limit))


def clear_expansion_cache() -> None:
    _expand_query_cached.cache_clear()


def _cli_compare(args: argparse.Namespace) -> int:
    from solomon.opensearch.docs_search import search_documents_with_expansion
    from solomon.transport.config import get_opensearch_config

    config = get_opensearch_config()
    if config is None:
        print("OpenSearch not configured", file=sys.stderr)
        return 1
    filters = None
    if args.filters:
        filters = json.loads(args.filters)

    off = search_documents_with_expansion(
        config,
        args.query,
        top_k=10,
        filters=filters,
        mode="hybrid",
        expand=False,
    )
    on = search_documents_with_expansion(
        config,
        args.query,
        top_k=10,
        filters=filters,
        mode="hybrid",
        expand=True,
        max_variants=doc_search_max_variants(),
    )
    print("=== expansion OFF ===")
    for i, d in enumerate(off.get("documents") or [], 1):
        print(i, d.get("chunk_id"), d.get("title"), d.get("score"))
    print("=== expansion ON ===")
    print("expanded:", on.get("expanded_queries"))
    for i, d in enumerate(on.get("documents") or [], 1):
        print(i, d.get("chunk_id"), d.get("matched_queries"), d.get("score"))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m solomon.opensearch.query_expansion")
    parser.add_argument("query", nargs="?", default="")
    parser.add_argument("--filters", default=None, help="JSON object")
    parser.add_argument("--max-variants", type=int, default=None)
    args = parser.parse_args()
    if not args.query:
        parser.print_help()
        raise SystemExit(0)
    from solomon.transport.config import get_opensearch_config

    if get_opensearch_config() is None:
        variants = expand_query(
            args.query,
            max_variants=args.max_variants or doc_search_max_variants(),
        )
        print(
            json.dumps(
                {"query": args.query, "variants": variants},
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(0)
    raise SystemExit(_cli_compare(args))


if __name__ == "__main__":
    main()


__all__ = [
    "expand_query",
    "build_expansion_prompt",
    "doc_search_expansion_enabled",
    "doc_search_max_variants",
    "clear_expansion_cache",
]
