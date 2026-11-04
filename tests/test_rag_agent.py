"""Knowledge RAG ReAct agent tests (no network)."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from solomon.rag import crew as rag_crew
from solomon.rag.agent import run_knowledge_agent
from solomon.rag.agent_tools import (
    run_graph_query,
    run_sql_query,
    validate_readonly_sql,
)
from solomon.rag.models import RetrievalPlan
from solomon.transport.config import LLMRoleConfig
from solomon.transport.user_context import UserContext


class BadRequestError(Exception):
    pass


@pytest.fixture
def rag_llm_config(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = LLMRoleConfig(
        role="agent:rag_agent",
        provider="openai",
        model="gpt-test",
        api_base="https://llm.example",
        api_key="sk-test",
        aws_region=None,
    )

    def _cfg(_k: str) -> LLMRoleConfig:
        return cfg

    monkeypatch.setattr("solomon.rag.agent.get_llm_agent_config", _cfg)
    monkeypatch.setattr("solomon.rag.crew.get_llm_agent_config", _cfg)
    monkeypatch.setattr("solomon.transport.llm.get_llm_agent_config", _cfg)


def _tool_call_response(
    *,
    thought: str,
    name: str,
    args: dict[str, Any],
    call_id: str = "call_1",
) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": thought,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _final_native(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


def _json_action(thought: str, action: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"thought": thought, "action": action, "args": args},
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


def _json_final(thought: str, answer: str) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"thought": thought, "final_answer": answer},
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }


class TestAgentToolScriptNative:
    def test_sql_graph_doc_sequence(
        self, monkeypatch: pytest.MonkeyPatch, rag_llm_config: None
    ) -> None:
        monkeypatch.setenv("SOLOMON_RAG_TOOL_MODE", "native")
        events: list[dict[str, Any]] = []
        sql_args = {"question": "count rows", "sql": "SELECT 1 AS n"}
        graph_args = {
            "cypher": "MATCH (l:Lot) RETURN l LIMIT 1",
            "params": {},
        }
        doc_args = {"query": "past quality issue", "top_k": 3}

        def fake_sql(args: dict[str, Any]) -> dict[str, Any]:
            return {
                "status": "ok",
                "sql": args.get("sql"),
                "columns": ["n"],
                "rows": [[1]],
                "row_count": 1,
            }

        def fake_graph(args: dict[str, Any]) -> dict[str, Any]:
            return {"status": "ok", "records": [{"l": {"lot_id": "L1"}}], "count": 1}

        def fake_doc(args: dict[str, Any]) -> dict[str, Any]:
            return {
                "status": "ok",
                "documents": [
                    {
                        "doc_id": "d1",
                        "title": "Report",
                        "snippet": "similar case",
                        "score": 0.9,
                        "metadata": {},
                    }
                ],
                "count": 1,
            }

        from solomon.rag import agent_tools

        monkeypatch.setattr(agent_tools, "run_sql_query", lambda _u, **kw: fake_sql(kw))
        monkeypatch.setattr(agent_tools, "run_graph_query", lambda _u, **kw: fake_graph(kw))
        monkeypatch.setattr(agent_tools, "run_doc_search", lambda _u, **kw: fake_doc(kw))

        calls: list[dict[str, Any]] = []

        def fake_completion(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            n = len(calls)
            if n == 1:
                return _tool_call_response(thought="SQL first", name="sql_query", args=sql_args)
            if n == 2:
                return _tool_call_response(
                    thought="Graph next",
                    name="graph_query",
                    args=graph_args,
                    call_id="call_2",
                )
            if n == 3:
                return _tool_call_response(
                    thought="Docs",
                    name="doc_search",
                    args=doc_args,
                    call_id="call_3",
                )
            return _final_native("## 結論\nok")

        monkeypatch.setattr("solomon.rag.agent._litellm_completion", fake_completion)
        monkeypatch.setattr(
            "solomon.rag.agent.build_system_prompt", lambda **_kw: "system"
        )

        result = run_knowledge_agent(
            "trace quality",
            user_ctx=None,  # type: ignore[arg-type]
            on_event=events.append,
            max_steps=8,
        )

        assert result.plan.strategy == "AGENT"
        assert len(result.tool_calls) == 3
        assert result.tool_calls[0]["name"] == "sql_query"
        assert result.tool_calls[1]["name"] == "graph_query"
        assert result.tool_calls[2]["name"] == "doc_search"
        assert len(result.bundle.hits) == 3
        assert any(e["type"] == "tool_start" for e in events)
        assert "## 結論" in result.answer_markdown


class TestAgentToolScriptJson:
    def test_json_mode_sequence(
        self, monkeypatch: pytest.MonkeyPatch, rag_llm_config: None
    ) -> None:
        monkeypatch.setenv("SOLOMON_RAG_TOOL_MODE", "json")
        from solomon.rag import agent_tools

        monkeypatch.setattr(
            agent_tools,
            "run_sql_query",
            lambda _u, **kw: {
                "status": "ok",
                "sql": "SELECT 1",
                "rows": [[1]],
                "row_count": 1,
            },
        )
        monkeypatch.setattr(
            agent_tools,
            "run_graph_query",
            lambda _u, **kw: {"status": "ok", "records": [], "count": 0},
        )

        seq = [
            _json_action("t1", "sql_query", {"question": "q"}),
            _json_action(
                "t2",
                "graph_query",
                {"cypher": "MATCH (n) RETURN n LIMIT 1", "params": {}},
            ),
            _json_final("t3", "## 答え\n完了"),
        ]

        def fake_completion(**kwargs: Any) -> dict[str, Any]:
            return seq.pop(0)

        monkeypatch.setattr("solomon.rag.agent._litellm_completion", fake_completion)
        monkeypatch.setattr("solomon.rag.agent.build_system_prompt", lambda **_kw: "sys")

        result = run_knowledge_agent(
            "question",
            user_ctx=None,  # type: ignore[arg-type]
        )
        assert len(result.tool_calls) == 2
        assert "完了" in result.answer_markdown


_QWEN_XML_CONTENT = (
    "We need to find SX-5 abnormal noise complaints.\n\n"
    "Let's do that. </think> <tool_call> <function=sql_query> "
    "<parameter=question> Show sample rows from field_claims </parameter> "
    "<parameter=sql> SELECT * FROM iceberg.mfg_quality.field_claims LIMIT 5 "
    "</parameter> </function> </tool_call>"
)


class TestTextToolCalls:
    def test_strip_reasoning(self) -> None:
        from solomon.rag.agent import _strip_reasoning

        assert _strip_reasoning("<think>a</think>b") == "b"
        assert _strip_reasoning("a\n</think>\nb") == "b"
        assert _strip_reasoning("plain") == "plain"
        assert _strip_reasoning(None) == ""

    def test_parse_qwen_xml(self) -> None:
        from solomon.rag.agent import _parse_text_tool_calls, _strip_reasoning

        remaining, calls = _parse_text_tool_calls(
            _strip_reasoning(_QWEN_XML_CONTENT), ["sql_query"]
        )
        assert remaining == ""
        assert len(calls) == 1
        args = json.loads(calls[0]["function"]["arguments"])
        assert calls[0]["function"]["name"] == "sql_query"
        assert args == {
            "question": "Show sample rows from field_claims",
            "sql": "SELECT * FROM iceberg.mfg_quality.field_claims LIMIT 5",
        }

    def test_parse_hermes_json_and_unclosed(self) -> None:
        from solomon.rag.agent import _parse_text_tool_calls

        _, calls = _parse_text_tool_calls(
            'x <tool_call>{"name": "doc_search", "arguments": {"query": "q", "top_k": 3}}'
            "</tool_call>",
            ["doc_search"],
        )
        assert json.loads(calls[0]["function"]["arguments"]) == {"query": "q", "top_k": 3}

        _, calls = _parse_text_tool_calls(
            "<tool_call>\n<function=doc_search>\n<parameter=query>\nabc\n"
            "<parameter=top_k>\n4\n",
            ["doc_search"],
        )
        assert json.loads(calls[0]["function"]["arguments"]) == {"query": "abc", "top_k": 4}

    def test_native_executes_text_tool_call(
        self, monkeypatch: pytest.MonkeyPatch, rag_llm_config: None
    ) -> None:
        monkeypatch.setenv("SOLOMON_RAG_TOOL_MODE", "native")
        from solomon.rag import agent_tools

        seen: list[dict[str, Any]] = []

        def fake_sql(_u: Any, **kw: Any) -> dict[str, Any]:
            seen.append(kw)
            return {
                "status": "ok",
                "sql": kw.get("sql"),
                "columns": ["claim_id"],
                "rows": [["C1"]],
                "row_count": 1,
            }

        monkeypatch.setattr(agent_tools, "run_sql_query", fake_sql)
        calls: list[dict[str, Any]] = []

        def fake_completion(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            if len(calls) == 1:
                return _final_native(_QWEN_XML_CONTENT)
            return _final_native("思考</think>## 結論\nC1")

        monkeypatch.setattr("solomon.rag.agent._litellm_completion", fake_completion)
        monkeypatch.setattr("solomon.rag.agent.build_system_prompt", lambda **_kw: "sys")

        result = run_knowledge_agent("q", user_ctx=None)  # type: ignore[arg-type]

        assert len(result.tool_calls) == 1
        assert seen[0]["sql"] == "SELECT * FROM iceberg.mfg_quality.field_claims LIMIT 5"
        assert len(result.bundle.hits) == 1
        assert any(m.get("role") == "tool" for m in calls[1]["messages"])
        assert "## 結論" in result.answer_markdown
        assert "</think>" not in result.answer_markdown
        assert "<tool_call>" not in result.answer_markdown

    def test_unknown_text_tool_is_not_executed(
        self, monkeypatch: pytest.MonkeyPatch, rag_llm_config: None
    ) -> None:
        monkeypatch.setenv("SOLOMON_RAG_TOOL_MODE", "native")
        from solomon.rag import agent_tools

        monkeypatch.setattr(
            agent_tools,
            "run_sql_query",
            lambda _u, **kw: pytest.fail("should not run"),
        )
        monkeypatch.setattr(
            "solomon.rag.agent._litellm_completion",
            lambda **kw: _final_native(
                "## 結論\nok <tool_call><function=rm_rf></function></tool_call>"
            ),
        )
        monkeypatch.setattr("solomon.rag.agent.build_system_prompt", lambda **_kw: "sys")

        result = run_knowledge_agent("q", user_ctx=None)  # type: ignore[arg-type]
        assert result.tool_calls == []
        assert "## 結論" in result.answer_markdown

    def test_json_mode_with_think_prefix(
        self, monkeypatch: pytest.MonkeyPatch, rag_llm_config: None
    ) -> None:
        monkeypatch.setenv("SOLOMON_RAG_TOOL_MODE", "json")
        monkeypatch.setattr(
            "solomon.rag.agent._litellm_completion",
            lambda **kw: _final_native(
                'thinking</think>{"thought": "t", "final_answer": "## json ok"}'
            ),
        )
        monkeypatch.setattr("solomon.rag.agent.build_system_prompt", lambda **_kw: "sys")

        result = run_knowledge_agent("q", user_ctx=None)  # type: ignore[arg-type]
        assert "json ok" in result.answer_markdown


class TestAutoFallback:
    def test_native_tools_error_falls_back_to_json(
        self, monkeypatch: pytest.MonkeyPatch, rag_llm_config: None
    ) -> None:
        monkeypatch.setenv("SOLOMON_RAG_TOOL_MODE", "auto")
        from solomon.rag import agent_tools

        monkeypatch.setattr(
            agent_tools,
            "run_sql_query",
            lambda _u, **kw: {"status": "ok", "sql": "SELECT 1", "rows": [], "row_count": 0},
        )

        calls = {"n": 0}

        def fake_completion(**kwargs: Any) -> dict[str, Any]:
            calls["n"] += 1
            if "tools" in kwargs:
                raise BadRequestError("tools unsupported")
            return _json_final("ok", "## fallback json")

        monkeypatch.setattr("solomon.rag.agent._litellm_completion", fake_completion)
        monkeypatch.setattr(
            "solomon.rag.agent._is_tools_unsupported",
            lambda e: isinstance(e, BadRequestError),
        )
        monkeypatch.setattr("solomon.rag.agent.build_system_prompt", lambda **_kw: "sys")

        result = run_knowledge_agent("q", user_ctx=None)  # type: ignore[arg-type]
        assert calls["n"] >= 2
        assert "fallback json" in result.answer_markdown


class TestMaxSteps:
    def test_final_answer_when_max_steps_reached(
        self, monkeypatch: pytest.MonkeyPatch, rag_llm_config: None
    ) -> None:
        monkeypatch.setenv("SOLOMON_RAG_TOOL_MODE", "json")
        from solomon.rag import agent_tools

        monkeypatch.setattr(
            agent_tools,
            "run_sql_query",
            lambda _u, **kw: {"status": "ok", "sql": "SELECT 1", "rows": [], "row_count": 0},
        )

        def fake_completion(**kwargs: Any) -> dict[str, Any]:
            user_msgs = [m for m in kwargs["messages"] if m.get("role") == "user"]
            if any("最大手数" in str(m.get("content")) for m in user_msgs):
                return _json_final("wrap", "## 打ち切り\n要約")
            return _json_action("loop", "sql_query", {"question": "again"})

        monkeypatch.setattr("solomon.rag.agent._litellm_completion", fake_completion)
        monkeypatch.setattr("solomon.rag.agent.build_system_prompt", lambda **_kw: "sys")

        result = run_knowledge_agent(
            "q",
            user_ctx=None,  # type: ignore[arg-type]
            max_steps=2,
        )
        assert "打ち切り" in result.answer_markdown


class TestReadonlyGuards:
    def test_rejects_write_sql(self) -> None:
        assert validate_readonly_sql("INSERT INTO t VALUES (1)") is not None
        out = run_sql_query(None, question="x", sql="DELETE FROM t")
        assert out["status"] == "error"

    def test_rejects_mutating_cypher(self) -> None:
        out = run_graph_query(None, cypher="CREATE (n:Lot)")
        assert out["status"] == "error"


class TestToolCache:
    def test_duplicate_tool_uses_cache(
        self, monkeypatch: pytest.MonkeyPatch, rag_llm_config: None
    ) -> None:
        monkeypatch.setenv("SOLOMON_RAG_TOOL_MODE", "json")
        from solomon.rag import agent_tools

        counter = {"n": 0}

        def counting_sql(_u: Any, **kw: Any) -> dict[str, Any]:
            counter["n"] += 1
            return {"status": "ok", "sql": "SELECT 1", "rows": [], "row_count": 0}

        monkeypatch.setattr(agent_tools, "run_sql_query", counting_sql)

        same = {"question": "q", "sql": "SELECT 1"}
        seq = [
            _json_action("1", "sql_query", same),
            _json_action("2", "sql_query", same),
            _json_final("3", "## done"),
        ]

        monkeypatch.setattr(
            "solomon.rag.agent._litellm_completion",
            lambda **kw: seq.pop(0),
        )
        monkeypatch.setattr("solomon.rag.agent.build_system_prompt", lambda **_kw: "sys")

        run_knowledge_agent("q", user_ctx=None)  # type: ignore[arg-type]
        assert counter["n"] == 1


class TestRagSources:
    def test_default_agent_tools_table_only(self) -> None:
        from solomon.rag.agent_tools import default_agent_tools

        tools = default_agent_tools(None, frozenset({"table"}))
        assert [t.name for t in tools] == ["sql_query"]

    def test_default_agent_tools_all(self) -> None:
        from solomon.rag.agent_tools import default_agent_tools

        tools = default_agent_tools(None, frozenset({"table", "graph", "search"}))
        assert [t.name for t in tools] == [
            "sql_query",
            "graph_query",
            "doc_search",
        ]

    def test_system_prompt_mentions_disabled_sources(self) -> None:
        from solomon.rag.agent import build_system_prompt

        prompt = build_system_prompt(
            enabled_sources=frozenset({"table"}),
            disabled_sources=["graph", "search"],
            tool_names=["sql_query"],
        )
        assert "無効なソース" in prompt
        assert "graph" in prompt
        assert "このソース構成では特定できない" in prompt

    def test_system_prompt_omits_disabled_source_catalog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from solomon.rag.agent import build_system_prompt

        monkeypatch.setenv(
            "SOLOMON_SEMANTIC_ROOT",
            str(
                __import__("pathlib").Path(__file__).resolve().parent
                / "fixtures"
                / "semantic"
                / "sample_orders"
            ),
        )
        from solomon.semantic import store as store_mod

        store_mod.load_models(force=True)

        prompt = build_system_prompt(
            enabled_sources=frozenset({"table"}),
            disabled_sources=["graph", "search"],
            tool_names=["sql_query"],
        )
        assert "文書インデックス" not in prompt
        assert "グラフ実行スキーマ" not in prompt
        assert "テーブルカタログ" in prompt

    def test_text2sql_skips_opensearch_when_search_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from solomon.tools.text2sql import _gather_rag_context

        calls = {"n": 0}

        class _FakeOsTool:
            def run(self, **_: object) -> dict[str, object]:
                calls["n"] += 1
                return {"status": "ok", "results": []}

        monkeypatch.setattr(
            "solomon.tools.text2sql.OpenSearchKeywordSearchTool",
            _FakeOsTool,
        )
        monkeypatch.setattr(
            "solomon.tools.text2sql.get_opensearch_config",
            lambda: object(),
        )
        monkeypatch.setattr(
            "solomon.tools.text2sql.search_datasets",
            lambda *_a, **_k: [],
        )

        _gather_rag_context("question", None, use_search_context=False)
        assert calls["n"] == 0

        _gather_rag_context("question", None, use_search_context=True)
        assert calls["n"] == 1

    def test_kickoff_resolves_request_sources(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SOLOMON_RAG_ENGINE", "heuristic")
        monkeypatch.delenv("SOLOMON_RAG_SOURCES", raising=False)
        captured: dict[str, object] = {}

        def _exec(plan, *, user_ctx=None, enabled_sources=None):
            captured["enabled"] = enabled_sources
            from solomon.rag.models import RetrievalBundle

            return RetrievalBundle(plan=plan, hits=[], disabled_sources=[])

        monkeypatch.setattr("solomon.rag.crew.execute_retrieval", _exec)
        monkeypatch.setattr(
            "solomon.rag.crew.classify_retrieval",
            lambda _q: RetrievalPlan(strategy="KEYWORD", query="q"),
        )
        monkeypatch.setattr(
            "solomon.rag.crew.synthesize_answer",
            lambda bundle: __import__(
                "solomon.rag.models", fromlist=["KnowledgeRagResult"]
            ).KnowledgeRagResult(
                plan=bundle.plan,
                bundle=bundle,
                answer_markdown="ok",
            ),
        )

        ctx = UserContext(user_name="u", groups=[], knox_jwt=None)
        out = rag_crew.kickoff_knowledge_rag(
            user_ctx=ctx, prompt="q", sources=["table", "graph"]
        )
        assert out["sources"] == ["graph", "table"] or sorted(out["sources"]) == [
            "graph",
            "table",
        ]
        assert captured["enabled"] == frozenset({"table", "graph"})
        assert out["disabled_sources"] == ["search"]


class TestHeuristicEngine:
    def test_heuristic_env_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SOLOMON_RAG_ENGINE", "heuristic")
        monkeypatch.setattr(
            "solomon.rag.crew.get_llm_agent_config",
            lambda _k: LLMRoleConfig(
                role="agent:rag_agent",
                provider="openai",
                model="gpt",
                api_base=None,
                api_key="sk",
                aws_region=None,
            ),
        )
        plan = RetrievalPlan(strategy="KEYWORD", query="sales revenue")
        monkeypatch.setattr(
            "solomon.rag.crew.execute_retrieval",
            lambda p, user_ctx=None, enabled_sources=None: __import__(
                "solomon.rag.models", fromlist=["RetrievalBundle"]
            ).RetrievalBundle(plan=p, hits=[]),
        )
        monkeypatch.setattr(
            "solomon.rag.crew.classify_retrieval",
            lambda _q: plan,
        )
        monkeypatch.setattr(
            "solomon.rag.crew.synthesize_answer",
            lambda bundle: __import__(
                "solomon.rag.models", fromlist=["KnowledgeRagResult"]
            ).KnowledgeRagResult(
                plan=bundle.plan,
                bundle=bundle,
                answer_markdown="heuristic ok",
            ),
        )

        ctx = UserContext(user_name="tester", groups=[], knox_jwt=None)
        out = rag_crew.kickoff_knowledge_rag(user_ctx=ctx, prompt="test")
        assert out["engine"] == "heuristic"
        assert out["strategy"] == "KEYWORD"
        assert out["answer_markdown"] == "heuristic ok"
