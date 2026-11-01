"""Router Crew の Task 定義 (Sequential, 2 タスク)。

  1. classify_intent_task   -> IntentClassification
  2. dispatch_task          -> DispatchPlan
"""
from __future__ import annotations

from typing import Any

from solomon.router.models import DispatchPlan, IntentClassification

try:
    from crewai import Task  # type: ignore
except Exception:  # pragma: no cover
    class Task:  # type: ignore[no-redef]
        """crewai.Task のスタブ。属性を保持するだけ。"""

        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)


def make_classify_intent_task(agent: Any) -> Task:
    return Task(
        description=(
            "以下のユーザー発話を分類せよ。\n"
            "\n"
            "USER PROMPT:\n"
            "{prompt}\n"
            "\n"
            "SESSION_ID: {session_id}\n"
            "\n"
            "手順:\n"
            "1) 発話に s3:// や『取り込み』『インジェスト』等が含まれる場合は "
            "intent='UNKNOWN', needs_clarification=true とし、"
            "clarification_prompt に「データ取り込みは別プロジェクト」と案内する。\n"
            "2) 発話に『サマリー』『まとめて』『どんな傾向』等が含まれ、"
            "対象テーブルが明示されているか代名詞 (『そのテーブル』等) が"
            "使われていれば intent='ANALYZE_SUMMARY'。代名詞は "
            "entity_memory_read tool を呼んで last_table を引き当て、"
            "extracted_args.fq_table_name に埋める。\n"
            "3) 発話に『ダッシュボード』『可視化』『グラフを作って』等が"
            "含まれれば intent='ANALYZE_DASHBOARD'。同様に fq_table_name "
            "を entity_memory で解決する。\n"
            "4) PuppyGraph / OpenSearch / 設計書・用語・障害などナレッジ横断質問は "
            "intent='KNOWLEDGE_RAG'。\n"
            "5) 挨拶・ヘルプ要求・意図不明な雑談は intent='CHITCHAT'。\n"
            "6) 上記いずれにも当てはまらないが情報が足りない場合は "
            "intent='UNKNOWN' とし、needs_clarification=true, "
            "clarification_prompt に日本語で追加質問を書く。\n"
            "\n"
            "extracted_args に Knox JWT / STS / パスワード等の秘匿情報は"
            "絶対に含めない。confidence は 0.0-1.0 の float で自信度を入れる。"
        ),
        expected_output=(
            "IntentClassification の JSON。intent, confidence, extracted_args, "
            "needs_clarification, clarification_prompt, reasoning を含む。"
        ),
        agent=agent,
        output_json=IntentClassification,
        max_retries=1,
    )


def make_dispatch_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "前段の IntentClassification を、Python 側が実行できる "
            "DispatchPlan に変換せよ。\n"
            "\n"
            "変換ルール:\n"
            "  intent=ANALYZE_SUMMARY   -> child_crew='analytics_summary', "
            "inputs={{fq_table_name, question}}, skip_child=false\n"
            "  intent=ANALYZE_DASHBOARD -> child_crew='analytics_dashboard', "
            "inputs={{fq_table_name, question}}, skip_child=false\n"
            "  intent=KNOWLEDGE_RAG     -> child_crew='knowledge_rag', "
            "inputs={{question}}, skip_child=false\n"
            "  intent=CHITCHAT          -> child_crew='chitchat', skip_child=false, "
            "inputs={{prompt}}\n"
            "  intent=UNKNOWN or needs_clarification=true -> child_crew='none', "
            "skip_child=true, response_markdown に clarification_prompt を書く\n"
            "\n"
            "重要: kickoff Tool は使わない。DispatchPlan の JSON のみ返す。"
        ),
        expected_output=(
            "DispatchPlan の JSON。intent, child_crew, inputs, "
            "response_markdown, skip_child を含む。"
        ),
        agent=agent,
        context=context,
        output_json=DispatchPlan,
        max_retries=1,
    )


__all__ = ["make_classify_intent_task", "make_dispatch_task"]
