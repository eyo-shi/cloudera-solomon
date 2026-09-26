"""Agentic RAG のデータモデル。"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

RetrievalStrategy = Literal[
    "GRAPH_QUERY",
    "SQL_ANALYTICS",
    "KEYWORD",
    "HYBRID",
    "COMPOSITE",
]


class RetrievalPlan(BaseModel):
    """Knowledge Router が決定する検索戦略。"""

    model_config = ConfigDict(extra="ignore")

    strategy: RetrievalStrategy
    query: str
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    reasoning: Optional[str] = None
    #: SQL_ANALYTICS 用: 対象 fq_table_name (Ossie / OpenSearch から推定)
    fq_table_hint: Optional[str] = None
    #: GRAPH_QUERY 用: Dataset / System 名のヒント
    entity_hint: Optional[str] = None


class SourceHit(BaseModel):
    """1 つの Knowledge Source からのヒット。"""

    source: Literal["neo4j", "opensearch", "lakehouse", "ossie"]
    kind: str
    score: Optional[float] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RetrievalBundle(BaseModel):
    """複数ソースの検索結果を束ねた中間表現。"""

    plan: RetrievalPlan
    hits: list[SourceHit] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


class KnowledgeRagResult(BaseModel):
    """kickoff_knowledge_rag の最終出力。"""

    plan: RetrievalPlan
    bundle: RetrievalBundle
    answer_markdown: str = ""
    sql_executed: Optional[str] = None
