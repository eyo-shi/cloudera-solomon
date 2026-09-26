"""Knowledge Router — 質問を RetrievalStrategy に分類する。"""

from __future__ import annotations

import re

from solomon.rag.models import RetrievalPlan, RetrievalStrategy

_GRAPH_PATTERNS = (
    r"呼び出",
    r"リネージ",
    r"lineage",
    r"関連.*テーブル",
    r"グラフ",
    r"entity",
    r"relationship",
    r"どの.*テーブル",
    r"dbテーブル",
)
_SQL_PATTERNS = (
    r"最多",
    r"ランキング",
    r"集計",
    r"件数",
    r"\d{4}年度",
    r"推移",
    r"top\s*\d",
    r"count",
    r"ranking",
    r"最も.*多",
)
_KEYWORD_PATTERNS = (
    r"ccsid",
    r"文字化け",
    r"エラーコード",
    r"[A-Z]{2,}\s*\d{3,}",  # 略語+数字 (CCSID 1399 等)
)
_HYBRID_PATTERNS = (
    r"処理.*説明",
    r"フロー",
    r"更新.*処理",
    r"workflow",
    r"how\s",
    r"説明して",
)
_COMPOSITE_PATTERNS = (
    r"まとめて",
    r"設計書",
    r"障害.*テーブル",
    r"関連する.*を",
    r"複合",
    r"横断",
)


def _matches(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _extract_entity_hint(prompt: str) -> str | None:
    m = re.search(r"システム\s*([A-Za-z0-9_\-\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]+)", prompt)
    if m:
        return m.group(1)
    m = re.search(r"([A-Za-z0-9_\-]+)\s*(?:から|の|と)", prompt)
    if m and len(m.group(1)) >= 2:
        return m.group(1)
    return None


def classify_retrieval(prompt: str) -> RetrievalPlan:
    """ヒューリスティックで RetrievalStrategy を決定する。

    LLM 経路は将来追加可能。テストと決定論的ルーティングのため Python 優先。
    """
    text = prompt.strip()
    lower = text.lower()

    if _matches(_COMPOSITE_PATTERNS, text):
        return RetrievalPlan(
            strategy="COMPOSITE",
            query=text,
            confidence=0.9,
            reasoning="composite keyword matched",
            entity_hint=_extract_entity_hint(text),
        )

    if _matches(_GRAPH_PATTERNS, text):
        return RetrievalPlan(
            strategy="GRAPH_QUERY",
            query=text,
            confidence=0.85,
            reasoning="graph/lineage keyword matched",
            entity_hint=_extract_entity_hint(text),
        )

    if _matches(_SQL_PATTERNS, text):
        return RetrievalPlan(
            strategy="SQL_ANALYTICS",
            query=text,
            confidence=0.85,
            reasoning="analytics/sql keyword matched",
        )

    if _matches(_KEYWORD_PATTERNS, text) or _matches(_KEYWORD_PATTERNS, lower):
        return RetrievalPlan(
            strategy="KEYWORD",
            query=text,
            confidence=0.8,
            reasoning="specific term / keyword pattern matched",
        )

    if _matches(_HYBRID_PATTERNS, text):
        return RetrievalPlan(
            strategy="HYBRID",
            query=text,
            confidence=0.75,
            reasoning="process/explanation keyword matched",
        )

    # デフォルト: 意味検索寄りの Hybrid
    return RetrievalPlan(
        strategy="HYBRID",
        query=text,
        confidence=0.5,
        reasoning="default to hybrid semantic search",
    )


def is_knowledge_query(prompt: str) -> bool:
    """Router 用: 取り込み/分析/雑談以外のナレッジ探索クエリか。"""
    text = prompt.strip()
    if not text:
        return False
    knowledge_markers = (
        *_GRAPH_PATTERNS,
        *_SQL_PATTERNS,
        *_KEYWORD_PATTERNS,
        *_HYBRID_PATTERNS,
        *_COMPOSITE_PATTERNS,
        r"検索",
        r"調べ",
        r"教えて",
        r"what is",
        r"find ",
    )
    return _matches(knowledge_markers, text)


__all__ = ["classify_retrieval", "is_knowledge_query"]
