"""CREATE 前の衝突・権限チェック (Trino Tool を直接呼ぶ — LLM 判定に依存しない)。"""
from __future__ import annotations

from solomon.ingestion.models import ConflictAndPermissionsResult
from solomon.tools.iceberg import TableExistsTool
from solomon.transport.errors import ErrorCode
from solomon.transport.trino_catalog import resolve_trino_catalog


def verify_create_gate(catalog: str, schema: str, table: str) -> ConflictAndPermissionsResult:
    """Iceberg テーブル作成前に存在確認する。新規テーブルでは TrinoMeta は不要。"""
    catalog = resolve_trino_catalog(catalog)
    resolved = f"{catalog}.{schema}.{table}"
    tool = TableExistsTool()
    res = tool._run(catalog=catalog, schema=schema, table=table)

    if res.get("status") == "ok":
        if res.get("exists"):
            return ConflictAndPermissionsResult(
                has_conflict=True,
                has_create_priv=False,
                resolved_table=resolved,
                error_code=ErrorCode.SCHEMA_NAME_CONFLICT.value,
                message="Table already exists.",
            )
        return ConflictAndPermissionsResult(
            has_conflict=False,
            has_create_priv=True,
            resolved_table=resolved,
        )

    message = str(res.get("message") or "Trino check failed")
    error_code = res.get("error_code")
    perm_denied = error_code in (
        ErrorCode.PERM_CREATE_DENIED.value,
        ErrorCode.PERM_UNKNOWN.value,
        ErrorCode.PERM_SELECT_DENIED.value,
    )
    return ConflictAndPermissionsResult(
        has_conflict=False,
        has_create_priv=not perm_denied,
        resolved_table=resolved,
        error_code=str(error_code) if error_code else ErrorCode.TRINO_QUERY_FAILED.value,
        message=message,
    )


def verify_create_gate_from_fq(fq_table: str) -> ConflictAndPermissionsResult | None:
    parts = fq_table.split(".")
    if len(parts) != 3:
        return None
    return verify_create_gate(parts[0], parts[1], parts[2])


__all__ = ["verify_create_gate", "verify_create_gate_from_fq"]
