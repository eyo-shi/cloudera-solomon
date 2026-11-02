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
            "ENTITY_MEMORY (safe keys only):\n"
            "{entity_memory_hint}\n"
            "\n"
            "## 接続済みソース (この環境で調べられるデータ)\n"
            "{source_catalog}\n"
            "\n"
            "## 業務コンテキスト\n"
            "{domain_context}\n"
            "\n"
            "## ルーティング例 (Ossie 例題)\n"
            "{routing_examples}\n"
            "\n"
            "判定基準:\n"
            "- 上記『接続済みソース』のテーブル・グラフ・文書を調べれば答えられる"
            "事実確認・調査・横断的な質問、およびそれらの事実を根拠にした"
            "報告書や文書のドラフト作成依頼は intent='KNOWLEDGE_RAG'。\n"
            "- catalog.schema.table 形式でテーブルが明示され、かつ要約・傾向・"
            "サマリー系の依頼だけを intent='ANALYZE_SUMMARY'。"
            "ダッシュボード・可視化・チャート作成の依頼で同様にテーブルが"
            "特定できる場合は intent='ANALYZE_DASHBOARD'。\n"
            "- 代名詞 (『そのテーブル』等) と要約/ダッシュボード語があり、"
            "entity_memory_read で last_table が取れる場合のみ ANALYZE_*。"
            "テーブル指定のない『まとめて』『グラフで見せて』は、接続済みソースで"
            "調べる質問なら KNOWLEDGE_RAG を優先。\n"
            "\n"
            "手順:\n"
            "1) s3:// や取り込み・インジェスト依頼 → intent='UNKNOWN', "
            "needs_clarification=true（別プロジェクト案内）。\n"
            "2) 上記判定基準で KNOWLEDGE_RAG / ANALYZE_* / CHITCHAT を選ぶ。\n"
            "3) 挨拶・ヘルプ・雑談 → intent='CHITCHAT'。\n"
            "4) 判別不能 → intent='UNKNOWN', needs_clarification=true。\n"
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
