"""Agentic RAG tests (no live Neo4j/OpenSearch/Trino required)."""

from __future__ import annotations

from solomon.rag.classifier import classify_retrieval, is_knowledge_query
from solomon.rag.models import RetrievalPlan
from solomon.rag.orchestrator import execute_retrieval
from solomon.rag.synthesizer import synthesize_answer
from solomon.router.crew import build_dispatch_plan, heuristic_classify
from solomon.tools.neo4j_query import validate_readonly_cypher


class TestRetrievalClassifier:
    def test_graph_query(self) -> None:
        plan = classify_retrieval("このシステムから呼び出されるDBテーブルは？")
        assert plan.strategy == "GRAPH_QUERY"

    def test_sql_analytics(self) -> None:
        plan = classify_retrieval("2025年度に最も障害が多かったシステムは？")
        assert plan.strategy == "SQL_ANALYTICS"

    def test_keyword(self) -> None:
        plan = classify_retrieval("CCSID 1399の文字化けについて")
        assert plan.strategy == "KEYWORD"

    def test_hybrid(self) -> None:
        plan = classify_retrieval("顧客情報を更新する処理について説明して")
        assert plan.strategy == "HYBRID"

    def test_composite(self) -> None:
        plan = classify_retrieval("システムAと関連する障害、設計書、DBテーブルをまとめて")
        assert plan.strategy == "COMPOSITE"


class TestRouterKnowledgeRag:
    def test_heuristic_routes_knowledge_rag(self) -> None:
        c = heuristic_classify("CCSID 1399の文字化けについて")
        assert c.intent == "KNOWLEDGE_RAG"
        plan = build_dispatch_plan(c)
        assert plan.child_crew == "knowledge_rag"
        assert plan.skip_child is False

    def test_is_knowledge_query(self) -> None:
        assert is_knowledge_query("設計書を検索して")
        assert not is_knowledge_query("s3://bucket/file.csv を取り込んで")


class TestNeo4jQueryValidation:
    def test_rejects_mutations(self) -> None:
        assert validate_readonly_cypher("CREATE (n:Node)") is not None

    def test_accepts_match(self) -> None:
        assert validate_readonly_cypher("MATCH (d:Dataset) RETURN d") is None


class TestOrchestratorOffline:
    def test_keyword_falls_back_to_ossie(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENSEARCH_ENDPOINT", raising=False)
        monkeypatch.delenv("OPENSEARCH_HOST", raising=False)
        plan = RetrievalPlan(strategy="KEYWORD", query="sales revenue")
        bundle = execute_retrieval(plan, user_ctx=None)
        assert bundle.plan.strategy == "KEYWORD"
        # ossie may return empty if no datasets — still ok
        assert isinstance(bundle.hits, list)

    def test_synthesizer_heuristic(self) -> None:
        from solomon.rag.models import RetrievalBundle, SourceHit

        bundle = RetrievalBundle(
            plan=RetrievalPlan(strategy="KEYWORD", query="test"),
            hits=[
                SourceHit(
                    source="ossie",
                    kind="tfidf",
                    score=0.5,
                    payload={"fq_name": "iceberg.demo.sales", "dataset": {"description": "Sales"}},
                )
            ],
        )
        result = synthesize_answer(bundle)
        assert "iceberg.demo.sales" in result.answer_markdown
