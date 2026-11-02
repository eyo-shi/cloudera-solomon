"""Ossie データセット検索 (英数字 + 日本語バイグラム TF-IDF)。"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from solomon.semantic.models import AIContext, OssieDataset, OssieSemanticModel

_ASCII_TOKEN = re.compile(r"[a-z0-9_]+", re.I)
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uF900-\uFAFF]")


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    lower = text.lower()
    tokens = _ASCII_TOKEN.findall(lower)
    chars = [c for c in text if _CJK.match(c)]
    for i in range(len(chars) - 1):
        tokens.append(chars[i] + chars[i + 1])
    if len(chars) == 1:
        tokens.append(chars[0])
    return tokens


def _ai_context_terms(ctx: AIContext | str | None) -> list[str]:
    if ctx is None:
        return []
    if isinstance(ctx, str):
        return tokenize(ctx)
    parts: list[str] = []
    if ctx.instructions:
        parts.extend(tokenize(ctx.instructions))
    for s in ctx.synonyms:
        parts.extend(tokenize(s))
    for ex in ctx.examples:
        parts.extend(tokenize(ex))
    return parts


def dataset_search_terms(model: OssieSemanticModel, dataset: OssieDataset) -> list[str]:
    parts: list[str] = []
    parts.extend(tokenize(dataset.name))
    if dataset.description:
        parts.extend(tokenize(dataset.description))
    parts.extend(_ai_context_terms(dataset.ai_context))
    for field in dataset.fields:
        parts.extend(tokenize(field.name))
        if field.label:
            parts.extend(tokenize(field.label))
        if field.description:
            parts.extend(tokenize(field.description))
        parts.extend(_ai_context_terms(field.ai_context))
    for metric in dataset.metrics:
        parts.extend(tokenize(metric.name))
        if metric.description:
            parts.extend(tokenize(metric.description))
        parts.extend(_ai_context_terms(metric.ai_context))
    parts.extend(_ai_context_terms(model.ai_context))
    if model.description:
        parts.extend(tokenize(model.description))
    return parts


def rank_datasets(
    query: str,
    entries: list[tuple[dict[str, Any], list[str]]],
    *,
    top_k: int = 3,
) -> list[tuple[float, dict[str, Any]]]:
    q_terms = tokenize(query)
    if not q_terms or not entries:
        return []
    q_counter = Counter(q_terms)
    corpus: list[tuple[dict[str, Any], Counter[str], list[str]]] = []
    for meta, terms in entries:
        corpus.append((meta, Counter(terms), terms))
    n_docs = len(corpus)
    df: Counter[str] = Counter()
    for _, tf, _ in corpus:
        for term in tf:
            df[term] += 1

    def score(tf: Counter[str], terms: list[str]) -> float:
        s = 0.0
        length = max(len(terms), 1)
        for term, qc in q_counter.items():
            if term not in tf:
                continue
            idf = math.log((n_docs + 1) / (df[term] + 1)) + 1.0
            s += qc * (tf[term] / length) * idf
        return s

    scored: list[tuple[float, dict[str, Any]]] = []
    for meta, tf, terms in corpus:
        sc = score(tf, terms)
        if sc > 0:
            scored.append((sc, meta))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_k]
