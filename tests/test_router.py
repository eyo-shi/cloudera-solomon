"""Router Crew の配線 + heuristic テスト (LLM なし)。"""
from __future__ import annotations

from pathlib import Path

import pytest

from solomon.router import (
    DispatchPlan,
    IntentClassification,
    RouterResult,
    build_dispatch_plan,
    build_router_crew,
    heuristic_classify,
    kickoff_router,
)
from solomon.router.agents import (
    make_dispatcher_agent,
    make_intent_classifier_agent,
)
from solomon.router.crew import (
    _DATA_INGEST_OUT_OF_SCOPE_MSG,
    _summarize_entity_memory,
)
from solomon.router.tasks import make_classify_intent_task
from solomon.router.tools import AnalyticsKickoffTool, EntityMemoryReadTool
from solomon.transport.user_context import UserContext

FIXTURE_SEMANTIC = (
    Path(__file__).resolve().parent / "fixtures" / "semantic" / "sample_orders"
)


def _reset_semantic_caches() -> None:
    from solomon.semantic import context as ctx_mod
    from solomon.semantic import store as store_mod
    from solomon.router import prompt_context as pc_mod
    from solomon.semantic import source_catalog as sc_mod

    store_mod.load_models(force=True)
    ctx_mod._cache_ctx = None
    sc_mod._cache_catalog = None
    pc_mod._cache_pack = None


@pytest.fixture(autouse=True)
def _router_semantic_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_SEMANTIC_ROOT", str(FIXTURE_SEMANTIC))
    _reset_semantic_caches()


def _tool_names(agent: object) -> set[str]:
    return {getattr(t, "name", "") for t in getattr(agent, "tools", [])}


def test_intent_classifier_has_entity_memory_tool() -> None:
    agent = make_intent_classifier_agent()
    assert _tool_names(agent) == {"entity_memory_read"}


def test_dispatcher_has_analytics_kickoff_tool() -> None:
    agent = make_dispatcher_agent()
    assert _tool_names(agent) == {"analytics_kickoff"}


def test_build_router_crew_has_two_tasks_sequential() -> None:
    crew = build_router_crew(memory=False)
    tasks = getattr(crew, "tasks", [])
    assert len(tasks) == 2
    t_classify, t_dispatch = tasks
    context = getattr(t_dispatch, "context", None) or []
    assert t_classify in context
    assert getattr(t_classify, "output_json", None) is IntentClassification
    assert getattr(t_dispatch, "output_json", None) is DispatchPlan


def test_heuristic_s3_ingest_is_out_of_scope() -> None:
    c = heuristic_classify(
        "s3://demo-bucket/2024/sales.xlsx を取り込んでテーブルにして"
    )
    assert c.intent == "UNKNOWN"
    assert c.needs_clarification is True
    assert _DATA_INGEST_OUT_OF_SCOPE_MSG in (c.clarification_prompt or "")


def test_heuristic_ingest_keyword_is_out_of_scope() -> None:
    c = heuristic_classify("何かを取り込みたい")
    assert c.intent == "UNKNOWN"
    assert c.needs_clarification is True


def test_heuristic_summary_uses_entity_memory() -> None:
    c = heuristic_classify(
        "そのテーブルをサマリーして",
        entity_memory={"last_table": "iceberg.demo.sales_2024"},
    )
    assert c.intent == "ANALYZE_SUMMARY"
    assert c.extracted_args["fq_table_name"] == "iceberg.demo.sales_2024"


def test_heuristic_dashboard_uses_entity_memory() -> None:
    c = heuristic_classify(
        "そのテーブルからダッシュボードを作って",
        entity_memory={"last_table": "iceberg.demo.sales_2024"},
    )
    assert c.intent == "ANALYZE_DASHBOARD"


def test_heuristic_chitchat() -> None:
    c = heuristic_classify("こんにちは、何ができるの?")
    assert c.intent == "CHITCHAT"


def test_heuristic_knowledge_rag_from_ossie_examples() -> None:
    c = heuristic_classify(
        "Which customers placed the most orders last month?"
    )
    assert c.intent == "KNOWLEDGE_RAG"


def test_heuristic_knowledge_rag_japanese_synonym() -> None:
    c = heuristic_classify("顧客は何人いますか？")
    assert c.intent == "KNOWLEDGE_RAG"


def test_heuristic_chitchat_off_domain() -> None:
    c = heuristic_classify("今日の天気はどう？")
    assert c.intent == "CHITCHAT"


def test_heuristic_summary_explicit_fq() -> None:
    c = heuristic_classify("iceberg.demo.orders をサマリーして")
    assert c.intent == "ANALYZE_SUMMARY"
    assert c.extracted_args.get("fq_table_name") == "iceberg.demo.orders"


def test_heuristic_summary_keywords_do_not_override_semantic_knowledge() -> None:
    c = heuristic_classify(
        "Which customers placed the most orders last month? 傾向をまとめて"
    )
    assert c.intent == "KNOWLEDGE_RAG"


def test_heuristic_empty_semantic_falls_back_to_legacy_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = Path(__file__).resolve().parent / "fixtures" / "semantic" / "empty_root"
    empty.mkdir(parents=True, exist_ok=True)
    (empty / "models").mkdir(exist_ok=True)
    monkeypatch.setenv("SOLOMON_SEMANTIC_ROOT", str(empty))
    _reset_semantic_caches()
    c = heuristic_classify("lineage を調べて")
    assert c.intent == "KNOWLEDGE_RAG"


def test_classify_intent_task_includes_semantic_placeholders() -> None:
    from solomon.router.agents import make_intent_classifier_agent
    from solomon.router.prompt_context import build_router_prompt_pack

    task = make_classify_intent_task(make_intent_classifier_agent())
    desc = str(getattr(task, "description", ""))
    assert "{domain_context}" in desc
    assert "{source_catalog}" in desc
    assert "{routing_examples}" in desc
    pack = build_router_prompt_pack(force=True)
    assert "sample_orders" in pack["domain_context"] or "order" in pack[
        "domain_context"
    ].lower()
    assert "KNOWLEDGE_RAG" in pack["routing_examples"]


def test_dispatch_plan_summary_no_table_asks_clarify() -> None:
    classification = IntentClassification(
        intent="ANALYZE_SUMMARY", confidence=0.6, extracted_args={}
    )
    plan = build_dispatch_plan(classification)
    assert plan.child_crew == "none"
    assert plan.skip_child is True


def test_dispatch_plan_dashboard_with_table() -> None:
    classification = IntentClassification(
        intent="ANALYZE_DASHBOARD",
        confidence=0.9,
        extracted_args={"fq_table_name": "iceberg.demo.t"},
    )
    plan = build_dispatch_plan(classification)
    assert plan.child_crew == "analytics_dashboard"
    assert plan.skip_child is False


def test_kickoff_router_heuristic_chitchat() -> None:
    ctx = UserContext(user_name="alice", groups=[], knox_jwt=None)
    result = kickoff_router(
        user_ctx=ctx,
        prompt="こんにちは",
        session_id="s1",
        entity_memory={},
        mode="heuristic",
    )
    assert result.classification.intent == "CHITCHAT"
    assert result.plan.child_crew == "chitchat"


def test_summarize_entity_memory_filters_unsafe_keys() -> None:
    memory = {
        "last_table": "iceberg.demo.sales_2024",
        "knox_jwt": "eyJ.SECRET.SIGNATURE",
    }
    summary = _summarize_entity_memory(memory)
    assert "iceberg.demo.sales_2024" in summary
    assert "SECRET" not in summary


def test_entity_memory_read_tool_returns_stored_snapshot() -> None:
    from solomon.api.state import get_store

    tool = EntityMemoryReadTool()
    store = get_store()
    sess = store.get_or_create_session("test_sess_router", "alice")
    store.update_entity_memory(
        sess.session_id, {"last_table": "iceberg.demo.sales_2024"}
    )
    result = tool._run(session_id=sess.session_id)
    assert result["status"] == "ok"
    assert result["entity_memory"]["last_table"] == "iceberg.demo.sales_2024"


def test_analytics_kickoff_tool_returns_not_implemented() -> None:
    from solomon.transport.user_context import reset_user_context, set_user_context

    tool = AnalyticsKickoffTool()
    ctx = UserContext(user_name="alice", groups=[], knox_jwt="tok")
    token = set_user_context(ctx)
    try:
        result = tool._run(mode="summary", fq_table_name="iceberg.demo.t")
    finally:
        reset_user_context(token)
    assert result["status"] == "error"
    assert result["error_code"] == "NOT_IMPLEMENTED"
