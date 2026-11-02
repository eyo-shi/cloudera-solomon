"""Agent answer scoring (normalization + key hit rate)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_text(text: str) -> str:
    """全角半角・空白・数値カンマを正規化。"""
    s = unicodedata.normalize("NFKC", text or "")
    s = s.replace(",", "").replace("，", "")
    s = re.sub(r"\s+", "", s)
    return s.lower()


def key_hit_rate(answer: str, keys: list[str]) -> dict[str, Any]:
    norm_answer = normalize_text(answer)
    hits: list[str] = []
    misses: list[str] = []
    for key in keys:
        nk = normalize_text(str(key))
        if not nk:
            continue
        if nk in norm_answer:
            hits.append(key)
        else:
            misses.append(key)
    total = len(hits) + len(misses)
    rate = (len(hits) / total) if total else 1.0
    return {
        "hits": hits,
        "misses": misses,
        "rate": rate,
        "total_keys": total,
    }


def grade_symbol(rate: float, *, full: float = 1.0, good: float = 0.8, partial: float = 0.5) -> str:
    """◎ / ○ / △ / × の判定（README 基準: ◎ = 80% 以上のキー含有）。"""
    if rate >= full and full > 0:
        return "◎"
    if rate >= good:
        return "◎"
    if rate >= partial:
        return "○"
    if rate > 0:
        return "△"
    return "×"


def forbidden_violations(answer: str, forbidden: list[str]) -> list[str]:
    norm = normalize_text(answer)
    bad: list[str] = []
    for term in forbidden:
        if normalize_text(term) in norm:
            bad.append(term)
    return bad


__all__ = ["normalize_text", "key_hit_rate", "grade_symbol", "forbidden_violations"]
