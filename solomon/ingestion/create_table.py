"""Iceberg CREATE — Tool 直呼び (LLM 出力欠落時の guardrail フォールバック)。"""
from __future__ import annotations

from typing import Any, Optional

from solomon.ingestion.models import (
    ConflictAndPermissionsResult,
    CreateIcebergTableResult,
    ProposeSchemaAndNameResult,
)
from solomon.tools.iceberg import IcebergCreateTableTool
from solomon.transport.trino_catalog import resolve_trino_catalog


def execute_create_iceberg_from_proposal(
    propose: ProposeSchemaAndNameResult,
    check: ConflictAndPermissionsResult,
) -> CreateIcebergTableResult | dict[str, Any]:
    """propose + check から IcebergCreateTableTool を 1 回実行する。"""
    parts = check.resolved_table.split(".")
    if len(parts) == 3:
        catalog, schema, table = parts
    else:
        catalog = resolve_trino_catalog(propose.catalog)
        schema = propose.target_schema
        table = propose.proposed_table_name

    catalog = resolve_trino_catalog(catalog)
    columns = [
        {
            "name": c.name,
            "trino_type": c.trino_type,
            "nullable": c.nullable,
        }
        for c in propose.columns
    ]
    tool_out = IcebergCreateTableTool()._run(
        catalog=catalog,
        schema=schema,
        table=table,
        columns=columns,
        partitioning=propose.partitioning or [],
        if_not_exists=True,
    )
    if tool_out.get("status") != "ok":
        return tool_out
    fq = str(tool_out.get("fq_table_name") or f"{catalog}.{schema}.{table}")
    ddl = str(tool_out.get("ddl") or "")
    column_count = int(tool_out.get("column_count") or len(columns))
    return CreateIcebergTableResult(
        fq_table_name=fq,
        ddl=ddl,
        column_count=column_count,
    )


def synthesize_create_result_if_table_exists(
    propose: ProposeSchemaAndNameResult,
    check: ConflictAndPermissionsResult,
) -> Optional[CreateIcebergTableResult]:
    """Tool 成功後に LLM が空出力のとき、存在確認済みなら結果を合成する。"""
    parts = check.resolved_table.split(".")
    if len(parts) != 3:
        return None
    catalog, schema, table = parts
    catalog = resolve_trino_catalog(catalog)
    return CreateIcebergTableResult(
        fq_table_name=f"{catalog}.{schema}.{table}",
        ddl=f'-- iceberg_create_table completed for "{catalog}"."{schema}"."{table}"',
        column_count=len(propose.columns),
    )


__all__ = [
    "execute_create_iceberg_from_proposal",
    "synthesize_create_result_if_table_exists",
]
