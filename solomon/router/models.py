"""Router Crew の Task 出力スキーマ (Pydantic v2)。

Router は 2 タスク固定:

  1. classify_intent_task   -> IntentClassification
  2. dispatch_task          -> DispatchPlan

Intent は 5 分類:

  * ``ANALYZE_SUMMARY``   — 既存テーブルへの Markdown サマリー要求
  * ``ANALYZE_DASHBOARD`` — 既存テーブルへのダッシュボード生成要求
  * ``KNOWLEDGE_RAG``     — Agentic RAG (Neo4j / OpenSearch / Lakehouse)
  * ``CHITCHAT``          — 挨拶・雑談・一般会話 (LLM 応答)
  * ``UNKNOWN``           — 判定不能。needs_clarification=True で聞き返す

データ取り込み (S3 → Iceberg / Neo4j / OpenSearch) は別プロジェクトの責務。
取り込み依頼は heuristic / clarify で案内する。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


IntentLiteral = Literal[
    "ANALYZE_SUMMARY",
    "ANALYZE_DASHBOARD",
    "KNOWLEDGE_RAG",
    "CHITCHAT",
    "UNKNOWN",
]


class IntentClassification(BaseModel):
    """ユーザー発話の意図分類結果。"""

    model_config = ConfigDict(extra="ignore")

    intent: IntentLiteral = Field(
        ...,
        description=(
            "ANALYZE_SUMMARY / ANALYZE_DASHBOARD / KNOWLEDGE_RAG / "
            "CHITCHAT / UNKNOWN"
        ),
    )
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    extracted_args: dict[str, Any] = Field(
        default_factory=dict,
        description="子 Crew に渡す引数。ANALYZE_* は fq_table_name を含む。",
    )
    needs_clarification: bool = Field(
        False,
        description="True なら子 Crew を起動せず、clarification_prompt をユーザーに投げる",
    )
    clarification_prompt: Optional[str] = Field(
        None, description="needs_clarification=True の場合のみ、ユーザーへの再質問"
    )
    reasoning: Optional[str] = Field(
        None, description="LLM の判定根拠 (デバッグ / ログ用)"
    )


class DispatchPlan(BaseModel):
    """`classify_intent` の結果を実行可能な子 Crew 呼び出しに変換した計画。"""

    model_config = ConfigDict(extra="ignore")

    intent: IntentLiteral
    child_crew: Literal[
        "analytics_summary",
        "analytics_dashboard",
        "knowledge_rag",
        "chitchat",
        "none",
    ]
    inputs: dict[str, Any] = Field(default_factory=dict)
    response_markdown: str = Field(
        "",
        description="CHITCHAT / needs_clarification 時に ChatPane に直接返すテキスト",
    )
    skip_child: bool = Field(
        False,
        description="True の場合、Python 側は子 Crew を起動しない (雑談 or 再質問)",
    )


class RouterResult(BaseModel):
    """`kickoff_router` の呼び出し側 (SSE ハンドラ等) が受け取る結果。"""

    model_config = ConfigDict(extra="ignore")

    classification: IntentClassification
    plan: DispatchPlan
    response_markdown: str = ""


__all__ = [
    "IntentLiteral",
    "IntentClassification",
    "DispatchPlan",
    "RouterResult",
]
