"""Trino カタログブラウザ API (`/api/catalog/*`)。

TreePane の左ペイン `iceberg` ルートに対応。Knox JWT でエンドユーザー
権限のクエリを行い、`information_schema` を叩く。

エンドポイント:

* ``GET /api/catalog/schemas``     — 全 schema
* ``GET /api/catalog/tables``      — schema 指定でテーブル一覧
* ``GET /api/catalog/columns``     — fully-qualified なテーブルのカラム定義
"""
from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from solomon.api.auth import require_user_context
from solomon.transport.config import get_trino_config
from solomon.transport.logging import get_logger
from solomon.transport.user_context import UserContext
from solomon.tools._trino_client import map_trino_error, trino_connection_for_user

router = APIRouter(prefix="/api/catalog", tags=["catalog"])
_logger = get_logger(__name__)

_TRINO_QUERY_TIMEOUT_S = 45.0


def _require_trino_or_503() -> None:
    """Trino 未設定なら 503 + guided error を投げる (UI が SetupGuide 表示)。"""
    if get_trino_config() is None:
        from solomon.trino.mode import is_internal_trino_mode

        if is_internal_trino_mode():
            instruction = (
                "warehouse-launcher の Status が running になるまで待ち、"
                "Application Log の Service ClusterIP を "
                "TRINO_ENDPOINT に設定して Solomon Application を再起動してください。"
            )
        else:
            instruction = (
                "Cloudera AI Workbench の Site Administration → Data "
                "Connections で CDW / Trino connection を登録し、Project "
                "→ Settings → Advanced → Environment Variables に "
                "TRINO_CONNECTION_NAME を設定して Application を"
                "再起動してください。"
            )
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "TRINO_NOT_CONFIGURED",
                "message": "Trino / CDW への接続情報が設定されていません。",
                "instruction": instruction,
            },
        )


def _internal_trino_instruction() -> str:
    return (
        "warehouse-launcher の Application Log で "
        "「Solomon TRINO_ENDPOINT (Service ClusterIP)」行を確認し、"
        "Project → Settings → Advanced → Environment Variables に "
        "TRINO_ENDPOINT=http://<Service ClusterIP>:8080 を設定して "
        "Solomon Application を再起動してください。"
    )


def _raise_trino_error(detail: dict[str, Any]) -> None:
    code = str(detail.get("error_code") or "")
    if code == "TRINO_NOT_CONFIGURED":
        detail.setdefault(
            "instruction",
            (
                "warehouse-launcher の Status が running になるまで待ち、"
                "Solomon Application を再起動してください。"
            ),
        )
        raise HTTPException(status_code=503, detail=detail)
    if code.startswith("TRINO_"):
        from solomon.trino.mode import is_internal_trino_mode

        if is_internal_trino_mode():
            detail.setdefault("instruction", _internal_trino_instruction())
    raise HTTPException(status_code=502, detail=detail)


def _run_query(
    user_ctx: UserContext,
    sql: str,
    catalog: str,
) -> list[list[Any]]:
    cfg = get_trino_config()
    conn_or_err = trino_connection_for_user(user_ctx, catalog=catalog)
    if isinstance(conn_or_err, dict):
        _raise_trino_error(conn_or_err)
    try:
        cur = conn_or_err.cursor()
        cur.execute(sql)
        return cur.fetchall()
    except Exception as e:  # noqa: BLE001
        host = f"{cfg.host}:{cfg.port}" if cfg else "unknown"
        _logger.error(
            "trino.catalog_query_failed",
            host=host,
            catalog=catalog,
            error=str(e),
        )
        _raise_trino_error(map_trino_error(e, sql))


async def _run_query_async(
    user_ctx: UserContext,
    sql: str,
    catalog: str,
) -> list[list[Any]]:
    """Trino 同期 I/O をスレッドに逃がし、API 全体の待ち時間に上限を設ける。"""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_query, user_ctx, sql, catalog),
            timeout=_TRINO_QUERY_TIMEOUT_S,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "TRINO_QUERY_FAILED",
                "message": (
                    f"Trino query timed out after {_TRINO_QUERY_TIMEOUT_S:.0f}s. "
                    "The cluster may still be waking from auto-suspend — wait a "
                    "few minutes and reload, or verify TRINO_HOST / "
                    "TRINO_CONNECTION_NAME."
                ),
            },
        ) from exc


@router.get("/schemas")
async def list_schemas(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    catalog: Annotated[str, Query(min_length=1, max_length=128)] = "iceberg",
) -> dict[str, Any]:
    _require_trino_or_503()
    sql = (
        f"SELECT schema_name FROM {catalog}.information_schema.schemata "
        "ORDER BY schema_name"
    )
    rows = await _run_query_async(user_ctx, sql, catalog)
    return {
        "catalog": catalog,
        "schemas": [r[0] for r in rows if r and r[0]],
    }


@router.get("/tables")
async def list_tables(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    schema: Annotated[str, Query(min_length=1, max_length=128)],
    catalog: Annotated[str, Query(min_length=1, max_length=128)] = "iceberg",
) -> dict[str, Any]:
    _require_trino_or_503()
    sql = (
        f"SELECT table_name, table_type "
        f"FROM {catalog}.information_schema.tables "
        f"WHERE table_schema = '{_esc(schema)}' "
        f"ORDER BY table_name"
    )
    rows = await _run_query_async(user_ctx, sql, catalog)
    return {
        "catalog": catalog,
        "schema": schema,
        "tables": [
            {"name": r[0], "type": r[1], "fq": f"{catalog}.{schema}.{r[0]}"}
            for r in rows
            if r and r[0]
        ],
    }


@router.get("/columns")
async def list_columns(
    user_ctx: Annotated[UserContext, Depends(require_user_context)],
    fq: Annotated[str, Query(min_length=3, max_length=256)],
) -> dict[str, Any]:
    """``fq`` は ``catalog.schema.table`` 形式。"""
    _require_trino_or_503()
    parts = fq.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "BAD_REQUEST",
                "message": "fq must be 'catalog.schema.table'",
            },
        )
    catalog, schema, table = parts
    sql = (
        f"SELECT column_name, data_type, is_nullable "
        f"FROM {catalog}.information_schema.columns "
        f"WHERE table_schema = '{_esc(schema)}' "
        f"  AND table_name = '{_esc(table)}' "
        f"ORDER BY ordinal_position"
    )
    rows = await _run_query_async(user_ctx, sql, catalog)
    return {
        "fq": fq,
        "columns": [
            {"name": r[0], "type": r[1], "nullable": (r[2] == "YES")}
            for r in rows
            if r and r[0]
        ],
    }


def _esc(s: str) -> str:
    """Trino 文字列リテラルの単純エスケープ。"""
    return s.replace("'", "''")
