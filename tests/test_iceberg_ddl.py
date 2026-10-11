"""IcebergCreateTableTool の DDL 生成 (internal DuckDB vs external Iceberg)。"""

from __future__ import annotations

from unittest import mock

import pytest

from solomon.tools.iceberg import ColumnDef, IcebergCreateTableTool, _build_create_ddl
from solomon.transport.user_context import UserContext, reset_user_context, set_user_context

_TRINO_CONN_PATCH = "solomon.tools.iceberg.trino_connection_for_user"


def _sample_cols() -> list[ColumnDef]:
    return [
        ColumnDef(name="id", trino_type="BIGINT", nullable=False),
        ColumnDef(name="note", trino_type="VARCHAR", nullable=True, comment="demo"),
    ]


def test_build_create_ddl_iceberg_external_style() -> None:
    ddl = _build_create_ddl(
        "iceberg",
        "demo",
        "quality_kanken",
        _sample_cols(),
        ["month(ts)"],
        "s3://bucket/prefix",
        True,
        internal_warehouse=False,
    )
    assert "WITH (" in ddl
    assert "format = 'PARQUET'" in ddl
    assert "partitioning = ARRAY" in ddl
    assert "location = 's3://bucket/prefix'" in ddl
    assert 'COMMENT \'demo\'' in ddl


def test_build_create_ddl_internal_warehouse_plain_create() -> None:
    ddl = _build_create_ddl(
        "iceberg",
        "demo",
        "quality_kanken",
        _sample_cols(),
        ["month(ts)"],
        "s3://bucket/prefix",
        True,
        internal_warehouse=True,
    )
    assert "WITH (" not in ddl
    assert "PARQUET" not in ddl
    assert "partitioning" not in ddl
    assert "location" not in ddl
    assert "COMMENT" not in ddl
    assert ddl.startswith('CREATE TABLE IF NOT EXISTS "iceberg"."demo"."quality_kanken"')
    assert '"id" BIGINT NOT NULL' in ddl


@pytest.fixture
def auth_ctx():
    ctx = UserContext(user_name="alice", knox_jwt="fake-jwt")
    token = set_user_context(ctx)
    yield ctx
    reset_user_context(token)


def test_create_table_tool_internal_runs_schema_then_plain_ddl(
    auth_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "solomon.tools.iceberg._use_internal_warehouse_ddl",
        lambda **_: True,
    )
    conn = mock.MagicMock()
    cur = conn.cursor.return_value
    monkeypatch.setattr(_TRINO_CONN_PATCH, lambda *_a, **_kw: conn)

    out = IcebergCreateTableTool()._run(
        catalog="iceberg",
        schema="demo",
        table="quality_kanken",
        columns=[{"name": "id", "trino_type": "BIGINT", "nullable": True}],
    )
    assert out.get("status") == "ok"
    assert cur.execute.call_count == 2
    schema_sql = cur.execute.call_args_list[0].args[0]
    ddl = cur.execute.call_args_list[1].args[0]
    assert "CREATE SCHEMA IF NOT EXISTS" in schema_sql
    assert "WITH (" not in ddl
