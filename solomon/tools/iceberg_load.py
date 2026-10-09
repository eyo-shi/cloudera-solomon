"""Iceberg テーブルへパース済みデータを INSERT する Tool。"""
from __future__ import annotations

import io
import re
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from solomon.tools._schema_args import coalesce_schema_field
from solomon.tools._s3_client import map_s3_error, s3_client_for_user
from solomon.tools._trino_client import trino_connection_for_user
from solomon.tools.kanken import kanken_rows_to_preview, parse_kanken_bytes
from solomon.transport.errors import ErrorCode, err, ok
from solomon.transport.trino_catalog import resolve_trino_catalog
from solomon.transport.tool_base import BaseSolomonTool
from solomon.transport.user_context import UserContext

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_INSERT_BATCH_SIZE = 50


class IcebergLoadDataArgs(BaseModel):
    catalog: str = Field("iceberg")
    schema_: str = Field(..., alias="schema")
    table: str
    bucket: str
    key: str
    format: str = Field(..., description="kanken / csv / tsv")
    encoding: Optional[str] = None
    delimiter: Optional[str] = None
    header_row: Optional[int] = Field(None, description="csv/tsv 用 (0-indexed)")

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize_schema(cls, data: Any) -> Any:
        return coalesce_schema_field(data)


class IcebergLoadDataTool(BaseSolomonTool):
    """CREATE 済み Iceberg テーブルへ S3 ファイルの行データを INSERT する。"""

    name: str = "iceberg_load_data"
    description: str = (
        "Load rows from an S3 file into an existing Iceberg table. Supports "
        "kanken (J5 完検) and csv/tsv. For kanken, Shift-JIS is auto-decoded "
        "and meta header rows are skipped. Callers MUST set max_retries=0."
    )
    args_schema: type[BaseModel] = IcebergLoadDataArgs

    def run(
        self,
        user_ctx: Optional[UserContext],
        catalog: str,
        schema: str,
        table: str,
        bucket: str,
        key: str,
        format: str,
        encoding: Optional[str] = None,
        delimiter: Optional[str] = None,
        header_row: Optional[int] = None,
        **_: Any,
    ) -> dict[str, Any]:
        catalog = resolve_trino_catalog(catalog)
        for ident in (catalog, schema, table):
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", ident):
                return err(
                    ErrorCode.SCHEMA_INFER_FAILED,
                    f"Invalid identifier: {ident!r}",
                )

        client = s3_client_for_user(user_ctx)
        if isinstance(client, dict):
            return client
        try:
            resp = client.get_object(Bucket=bucket, Key=key)
            body: bytes = resp["Body"].read()
        except Exception as e:  # noqa: BLE001
            return map_s3_error(e, bucket, key)

        fmt = format.lower()
        try:
            if fmt == "kanken":
                parsed = parse_kanken_bytes(body)
                preview = kanken_rows_to_preview(parsed, max_rows=100_000)
                rows = preview.get("preview_rows") or []
                columns = [c["name"] for c in preview.get("columns") or []]
            elif fmt in ("csv", "tsv"):
                rows, columns = _read_csv_rows(
                    body,
                    encoding=encoding,
                    delimiter=delimiter,
                    header_row=header_row,
                    fmt=fmt,
                )
            else:
                return err(
                    ErrorCode.FORMAT_UNSUPPORTED,
                    f"iceberg_load_data does not support format={format!r}",
                )
        except Exception as e:  # noqa: BLE001
            return err(ErrorCode.FORMAT_CORRUPT, f"failed to parse source file: {e}")

        if not rows:
            return err(ErrorCode.FORMAT_CORRUPT, "no data rows found in source file")

        col_map = _map_columns(columns, schema, table)
        if isinstance(col_map, dict) and col_map.get("status") == "error":
            return col_map

        conn_or_err = trino_connection_for_user(
            user_ctx, catalog=catalog, schema=schema
        )
        if isinstance(conn_or_err, dict):
            return conn_or_err

        inserted = 0
        try:
            cur = conn_or_err.cursor()
            for batch_start in range(0, len(rows), _INSERT_BATCH_SIZE):
                batch = rows[batch_start : batch_start + _INSERT_BATCH_SIZE]
                sql = _build_insert_sql(catalog, schema, table, col_map, batch)
                cur.execute(sql)
                if cur.description:
                    cur.fetchall()
                inserted += len(batch)
        except Exception as e:  # noqa: BLE001
            from solomon.tools.trino import map_trino_error

            return map_trino_error(e, f"INSERT INTO {catalog}.{schema}.{table}")

        return ok(
            {
                "fq_table_name": f"{catalog}.{schema}.{table}",
                "inserted_rows": inserted,
                "column_count": len(col_map),  # type: ignore[arg-type]
                "source_format": fmt,
            }
        )


def _read_csv_rows(
    body: bytes,
    *,
    encoding: Optional[str],
    delimiter: Optional[str],
    header_row: Optional[int],
    fmt: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    import pandas as pd  # type: ignore

    enc = encoding or "utf-8"
    sep = delimiter or ("\t" if fmt == "tsv" else ",")
    skip = list(range(header_row)) if header_row and header_row > 0 else None
    header = 0 if header_row is None else 0
    df = pd.read_csv(
        io.BytesIO(body),
        sep=sep,
        encoding=enc,
        skiprows=skip,
        header=header,
    )
    columns = [str(c) for c in df.columns]
    rows = [
        {str(k): _jsonify(v) for k, v in record.items()}
        for record in df.to_dict(orient="records")
    ]
    return rows, columns


def _map_columns(
    source_columns: list[str], schema: str, table: str
) -> list[str] | dict[str, Any]:
    mapped: list[str] = []
    for name in source_columns:
        safe = _sanitize_column(name)
        if not _IDENT_RE.match(safe):
            return err(
                ErrorCode.SCHEMA_INFER_FAILED,
                f"Cannot map column {name!r} to a valid Trino identifier",
            )
        mapped.append(safe)
    return mapped


def _sanitize_column(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "col"
    if cleaned[0].isdigit():
        cleaned = f"col_{cleaned}"
    return cleaned


def _build_insert_sql(
    catalog: str,
    schema: str,
    table: str,
    columns: list[str],
    rows: list[dict[str, Any]],
) -> str:
    col_sql = ", ".join(f'"{c}"' for c in columns)
    values_parts: list[str] = []
    for row in rows:
        vals = ", ".join(_sql_literal(row.get(col)) for col in columns)
        values_parts.append(f"({vals})")
    values_sql = ", ".join(values_parts)
    return (
        f'INSERT INTO "{catalog}"."{schema}"."{table}" ({col_sql}) VALUES {values_sql}'
    )


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return text
    escaped = text.replace("'", "''")
    return f"'{escaped}'"


def _jsonify(value: Any) -> Any:
    if value is None:
        return None
    try:
        import numpy as np  # type: ignore

        if isinstance(value, np.generic):
            return value.item()
    except ImportError:  # pragma: no cover
        pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            pass
    return value


__all__ = ["IcebergLoadDataTool"]
