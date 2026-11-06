"""Text2SQL schema context, guards, and Trino retry (mock LLM / Trino)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from solomon.rag.agent_tools import run_sql_query, validate_readonly_sql
from solomon.tools.schema_context import (
    build_schema_context,
    clear_schema_context_caches,
    fetch_columns_information_schema,
)
from solomon.tools.text2sql import (
    Text2SQLTool,
    execute_readonly_sql_with_retry,
    _build_sql_prompt,
)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "semantic" / "sample_orders"


@pytest.fixture(autouse=True)
def _semantic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_SEMANTIC_ROOT", str(FIXTURE_ROOT))
    from solomon.semantic import store as store_mod

    store_mod.load_models(force=True)
    from solomon.semantic import context as ctx_mod

    ctx_mod._cache_ctx = None
    clear_schema_context_caches()


def test_build_schema_context_includes_rich_metadata() -> None:
    ctx = build_schema_context(
        "order_line count by client",
        catalog="demo_catalog",
        schema="demo_schema",
    )
    assert "demo_catalog.demo_schema.customers" in ctx
    assert "demo_catalog.demo_schema.orders" in ctx
    assert "customer_id" in ctx
    assert "顧客名" in ctx or "client name" in ctx
    assert "Joins" in ctx
    assert "customer_id = orders.customer_id" in ctx
    assert "total_amount" in ctx or "SUM(amount)" in ctx
    assert "Verified query examples" in ctx
    assert "Total order count" in ctx


def test_build_schema_context_all_tables_when_under_max() -> None:
    ctx = build_schema_context(
        "anything",
        catalog="demo_catalog",
        schema="demo_schema",
        max_tables=20,
    )
    assert "customers" in ctx
    assert "orders" in ctx
    assert "support_notes" not in ctx


def test_build_schema_context_search_when_many_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solomon.tools import schema_context as sc_mod

    base = sc_mod._eligible_datasets("demo_catalog", "demo_schema")
    padded = list(base)
    for i in range(25):
        padded.append((base[0][0], base[0][1], f"demo_catalog.demo_schema.extra_{i}"))

    monkeypatch.setattr(sc_mod, "_eligible_datasets", lambda _c, _s: padded)
    monkeypatch.setattr(
        sc_mod,
        "search_datasets",
        lambda q, top_k=3: [
            {"fq_name": "demo_catalog.demo_schema.orders", "score": 1.0},
            {"fq_name": "demo_catalog.demo_schema.customers", "score": 0.9},
        ][:top_k],
    )

    ctx = build_schema_context(
        "注文 顧客",
        catalog="demo_catalog",
        schema="demo_schema",
        max_tables=2,
    )
    assert "orders" in ctx
    assert "customers" in ctx


def test_information_schema_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "solomon.tools.schema_context.load_models",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "solomon.tools.schema_context.fetch_columns_information_schema",
        lambda *_a, **_k: [{"name": "id", "type": "integer"}],
    )
    monkeypatch.setattr(
        "solomon.tools.schema_context._fallback_tables_from_information_schema",
        lambda *_a, **_k: [
            (None, None, "demo_catalog.demo_schema.customers"),
        ],
    )
    ctx = build_schema_context(
        "count rows",
        catalog="demo_catalog",
        schema="demo_schema",
    )
    assert "information_schema only" in ctx
    assert "id (integer)" in ctx


def test_fetch_columns_uses_cache() -> None:
    clear_schema_context_caches()
    from solomon.tools import schema_context as sc_mod

    sc_mod._COLUMN_CACHE[("c", "s", "t")] = [{"name": "x", "type": "int"}]
    cols = sc_mod.fetch_columns_information_schema("c", "s", "t")
    assert cols == [{"name": "x", "type": "int"}]


def test_japanese_question_ranks_related_tables() -> None:
    from solomon.semantic.store import search_datasets

    hits = search_datasets("先月 顧客 ごと 注文 件数", top_k=3)
    names = {h.get("name") for h in hits}
    assert "customers" in names or "orders" in names


def test_build_sql_prompt_uses_config_schema() -> None:
    prompt = _build_sql_prompt("q", "## Tables\n", "cat1", "sch2")
    assert "default schema: sch2" in prompt
    assert "DATE 'YYYY-MM-DD'" in prompt


def test_rejects_multistatement_sql() -> None:
    assert validate_readonly_sql("SELECT 1; SELECT 2") is not None
    assert validate_readonly_sql("SELECT 1") is None


def test_trino_error_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_calls: list[str] = []

    def fake_llm(prompt: str) -> tuple[str | None, str]:
        llm_calls.append(prompt)
        if len(llm_calls) == 1:
            return "SELECT bad_col FROM t LIMIT 10", "first"
        return "SELECT fixed FROM t LIMIT 10", "second"

    exec_calls: list[str] = []

    def fake_trino(_self: Any, **kwargs: Any) -> dict[str, Any]:
        sql = kwargs.get("sql", "")
        exec_calls.append(sql)
        if "bad_col" in sql:
            return {"status": "error", "message": "Column bad_col not found"}
        return {
            "status": "ok",
            "columns": [{"name": "x"}],
            "rows": [[1]],
            "row_count": 1,
        }

    monkeypatch.setattr(
        "solomon.tools.text2sql._llm_sql",
        fake_llm,
    )
    monkeypatch.setattr(
        "solomon.tools.text2sql.TrinoQueryTool.run",
        fake_trino,
    )
    monkeypatch.setattr(
        "solomon.tools.text2sql.build_schema_context",
        lambda *_a, **_k: "## Tables",
    )

    out = execute_readonly_sql_with_retry(
        None,
        question="how many",
        catalog="demo_catalog",
        schema="demo_schema",
        max_rows=10,
    )
    assert out["status"] == "ok"
    assert out["sql"] == "SELECT fixed FROM t LIMIT 10"
    assert len(out["attempts"]) == 1
    assert len(exec_calls) == 2
    assert len(llm_calls) == 2
    assert "Column bad_col not found" in llm_calls[1]


@pytest.mark.parametrize(
    "bad_sql",
    [
        "EXPLAIN ANALYZE INSERT INTO t VALUES (1)",
        "SELECT 1; DROP TABLE t",
        "CALL system.flush_metadata_cache()",
    ],
)
def test_retry_never_executes_sql_that_fails_guard(
    monkeypatch: pytest.MonkeyPatch, bad_sql: str
) -> None:
    """LLM の 1 回目が読み取り専用チェックに落ちたら、実行せずに書き直させる。"""
    llm_calls: list[str] = []

    def fake_llm(prompt: str) -> tuple[str | None, str]:
        llm_calls.append(prompt)
        return (bad_sql, "first") if len(llm_calls) == 1 else ("SELECT 1 FROM t LIMIT 10", "")

    exec_calls: list[str] = []

    def fake_trino(_self: Any, **kwargs: Any) -> dict[str, Any]:
        exec_calls.append(kwargs.get("sql", ""))
        return {"status": "ok", "columns": [{"name": "x"}], "rows": [[1]], "row_count": 1}

    monkeypatch.setattr("solomon.tools.text2sql._llm_sql", fake_llm)
    monkeypatch.setattr("solomon.tools.text2sql.TrinoQueryTool.run", fake_trino)
    monkeypatch.setattr("solomon.tools.text2sql.build_schema_context", lambda *_a, **_k: "## T")

    out = execute_readonly_sql_with_retry(
        None, question="q", catalog="demo_catalog", schema="demo_schema", max_rows=10
    )
    assert exec_calls == ["SELECT 1 FROM t LIMIT 10"]
    assert out["status"] == "ok"
    assert out["attempts"][0]["sql"] == bad_sql
    assert bad_sql in llm_calls[1]


def test_retry_gives_up_when_guard_fails_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    exec_calls: list[str] = []
    monkeypatch.setattr(
        "solomon.tools.text2sql._llm_sql", lambda _p: ("DELETE FROM t", "")
    )
    monkeypatch.setattr(
        "solomon.tools.text2sql.TrinoQueryTool.run",
        lambda _self, **kw: exec_calls.append(kw.get("sql", "")) or {"status": "ok"},
    )
    monkeypatch.setattr("solomon.tools.text2sql.build_schema_context", lambda *_a, **_k: "## T")

    out = execute_readonly_sql_with_retry(
        None, question="q", catalog="demo_catalog", schema="demo_schema", max_rows=10
    )
    assert out["status"] == "error"
    assert exec_calls == []
    assert len(out["attempts"]) == 2


def test_readonly_statement_allowlist() -> None:
    from solomon.tools.sql_guard import validate_readonly_sql, validate_readonly_statement

    for ok_sql in (
        "SELECT 1",
        "-- head\nWITH a AS (SELECT 1) SELECT * FROM a",
        "SHOW TABLES",
        "DESCRIBE iceberg.s.t",
        "EXPLAIN SELECT 1",
        "EXPLAIN ANALYZE VERBOSE SELECT 1",
        "EXPLAIN (TYPE DISTRIBUTED) SELECT 1",
    ):
        assert validate_readonly_statement(ok_sql) is None, ok_sql
    for bad_sql in (
        "/* x */ DROP TABLE t",
        "EXPLAIN ANALYZE INSERT INTO t VALUES (1)",
        "EXPLAIN (TYPE IO) DELETE FROM t",
        "SET SESSION a = 1",
        "RESET SESSION a",
        "USE iceberg.s",
        "CALL system.x()",
        "COMMENT ON TABLE t IS 'x'",
        "REFRESH MATERIALIZED VIEW v",
        "EXECUTE stmt",
        "START TRANSACTION",
        "SHOW TABLES; DROP TABLE t",
    ):
        assert validate_readonly_statement(bad_sql) is not None, bad_sql
    assert validate_readonly_sql("/* c */ SELECT 1") is None
    assert validate_readonly_sql("/* c */ DROP TABLE t") is not None
    assert validate_readonly_sql("SHOW TABLES") is not None


def test_run_sql_query_with_sql_uses_retry_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "solomon.rag.agent_tools.get_trino_config",
        lambda: mock.Mock(catalog="c", schema="s"),
    )
    seen: dict[str, Any] = {}

    def fake_pipeline(*_a: Any, **kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {
            "status": "ok",
            "sql": kwargs.get("sql"),
            "rows": [[1]],
            "row_count": 1,
            "attempts": [],
        }

    monkeypatch.setattr(
        "solomon.rag.agent_tools.execute_readonly_sql_with_retry",
        fake_pipeline,
    )

    out = run_sql_query(None, question="q", sql="SELECT 1")
    assert out["status"] == "ok"
    assert seen.get("sql") == "SELECT 1"
    assert seen.get("question") == "q"


def test_text2sql_uses_strong_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "solomon.tools.text2sql.get_trino_config",
        lambda: mock.Mock(catalog="demo_catalog", schema="demo_schema"),
    )
    captured: dict[str, Any] = {}

    def fake_json(prompt: str, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"sql": "SELECT 1 LIMIT 10", "reasoning": "ok"}

    monkeypatch.setattr(
        "solomon.tools.text2sql.try_json_completion",
        fake_json,
    )
    monkeypatch.setattr(
        "solomon.tools.text2sql.TrinoQueryTool.run",
        lambda *_s, **_k: {
            "status": "ok",
            "columns": [],
            "rows": [],
            "row_count": 0,
        },
    )

    Text2SQLTool().run(user_ctx=None, question="count orders")
    assert captured.get("agent_key") == "text2sql"
    assert captured.get("max_tokens") == 4096
    assert captured.get("timeout") == 60.0


def test_text2sql_generation_failure_is_an_error_not_a_substitute_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生成に失敗したとき、別の問い（任意テーブルの件数）を実行して ok を返さない。"""
    monkeypatch.setattr(
        "solomon.tools.text2sql.get_trino_config",
        lambda: mock.Mock(catalog="demo_catalog", schema="demo_schema"),
    )
    monkeypatch.setattr(
        "solomon.tools.text2sql.try_json_completion", lambda *_a, **_k: None
    )
    executed: list[Any] = []
    monkeypatch.setattr(
        "solomon.tools.text2sql.TrinoQueryTool.run",
        lambda _self, **kw: executed.append(kw.get("sql")) or {"status": "ok"},
    )

    out = Text2SQLTool().run(
        user_ctx=None,
        question="orders by region",
        fq_table_hint="demo_catalog.demo_schema.orders",
        use_search_context=False,
    )
    assert out["status"] == "error"
    assert "Could not generate SQL" in out["message"]
    assert executed == []


def test_run_sql_query_error_hints_explicit_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "solomon.rag.agent_tools.Text2SQLTool.run",
        lambda *_a, **_k: {"status": "error", "message": "Could not generate SQL from LLM."},
    )
    out = run_sql_query(None, question="q")
    assert out["status"] == "error"
    assert "sql 引数" in out["hint"]
