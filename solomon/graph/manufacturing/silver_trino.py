"""製造トレース QA — ``iceberg.inspection_silver`` (Trino) からサマリーを取得。"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

from solomon.transport.config import get_trino_config
from solomon.transport.user_context import UserContext

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def silver_schema_name() -> str:
    raw = (
        os.environ.get("SOLOMON_SILVER_SCHEMA")
        or os.environ.get("TRINO_SCHEMA")
        or "inspection_silver"
    ).strip()
    if not _IDENT_RE.match(raw):
        return "inspection_silver"
    return raw


def silver_catalog_name() -> str:
    cfg = get_trino_config()
    if cfg and cfg.catalog:
        return cfg.catalog
    return "iceberg"


def _fq(table: str) -> str:
    catalog = silver_catalog_name()
    schema = silver_schema_name()
    if not _IDENT_RE.match(table):
        raise ValueError(f"invalid table name: {table!r}")
    return f'"{catalog}"."{schema}"."{table}"'


def _scalar_query(conn: Any, sql: str) -> Any:
    cur = conn.cursor()
    cur.execute(sql)
    row = cur.fetchone()
    if row is None:
        return None
    return row[0]


def _row_query(conn: Any, sql: str) -> dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(sql)
    if not cur.description:
        return None
    names = [d[0] for d in cur.description]
    row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(names, row, strict=False))


def fetch_trace_summary_from_silver(
    trace_id: str,
    user_ctx: Optional[UserContext] = None,
) -> dict[str, Any] | None:
    """Trino で silver 表から出検・完検サマリーを取得。失敗時は None / error dict。"""
    from solomon.tools._trino_client import trino_connection_for_user

    cfg = get_trino_config()
    if cfg is None:
        return None

    tid = trace_id.replace("'", "''")
    shukken_t = _fq("silver_j5_shukken_id")
    id_fields_t = _fq("silver_id_fields")
    kanken_fields_t = _fq("silver_kanken_fields")
    kanken_t = _fq("silver_kanken")

    shukken_sql = f"""
SELECT
  json_extract_scalar(payload, '$.customer_hinban') AS customer_part_no,
  json_extract_scalar(payload, '$.passed_at') AS pass_datetime,
  COALESCE(
    TRY(CAST(json_extract_scalar(payload, '$.hex_line_count') AS BIGINT)),
    TRY(CAST(json_extract_scalar(payload, '$.hex_row_count') AS BIGINT))
  ) AS dump_row_count,
  object_key,
  etag
FROM {shukken_t}
WHERE trace_id = '{tid}'
ORDER BY ingested_at DESC
LIMIT 1
"""

    id_fields_sql = f"""
SELECT COUNT(*) AS cnt
FROM {id_fields_t}
WHERE trace_id = '{tid}'
  AND timing_band = 'shukken_out'
"""

    kanken_fields_sql = f"""
SELECT COUNT(*) AS cnt
FROM {kanken_fields_t}
WHERE trace_id = '{tid}'
"""

    kanken_payload_sql = f"""
SELECT TRY(CAST(json_extract_scalar(payload, '$.measurement_count') AS BIGINT)) AS measurement_count
FROM {kanken_t}
WHERE trace_id = '{tid}'
ORDER BY ingested_at DESC
LIMIT 1
"""

    conn_or_err = trino_connection_for_user(
        user_ctx,
        catalog=silver_catalog_name(),
        schema=silver_schema_name(),
    )
    if isinstance(conn_or_err, dict):
        return {"trace_id": trace_id, "error": conn_or_err.get("message", "TRINO_FAILED")}

    try:
        out: dict[str, Any] = {
            "trace_id": trace_id,
            "source": "lakehouse",
            "silver_schema": silver_schema_name(),
        }
        shukken = _row_query(conn_or_err, shukken_sql)
        if shukken:
            out["customer_part_no"] = shukken.get("customer_part_no")
            out["pass_datetime"] = shukken.get("pass_datetime")
            dump_rows = shukken.get("dump_row_count")
            if dump_rows is not None:
                out["dump_row_count"] = int(dump_rows)
            object_key = shukken.get("object_key")
            etag = shukken.get("etag")
            if object_key and etag:
                ok = str(object_key).replace("'", "''")
                eg = str(etag).replace("'", "''")
                scoped = f"""
SELECT COUNT(*) FROM {id_fields_t}
WHERE object_key = '{ok}' AND etag = '{eg}'
  AND timing_band = 'shukken_out'
"""
                scoped_cnt = _scalar_query(conn_or_err, scoped)
                if scoped_cnt is not None and int(scoped_cnt) > 0:
                    out["shukken_decoded_field_count"] = int(scoped_cnt)

        field_cnt = _scalar_query(conn_or_err, id_fields_sql)
        if field_cnt is not None and int(field_cnt) > 0:
            out["shukken_decoded_field_count"] = int(field_cnt)

        kanken_cnt = _scalar_query(conn_or_err, kanken_fields_sql)
        if kanken_cnt is not None and int(kanken_cnt) > 0:
            out["kanken_measurement_rows"] = int(kanken_cnt)
        else:
            payload_cnt = _scalar_query(conn_or_err, kanken_payload_sql)
            if payload_cnt is not None:
                out["kanken_measurement_rows"] = int(payload_cnt)

        has_data = any(
            out.get(k) is not None
            for k in (
                "customer_part_no",
                "dump_row_count",
                "shukken_decoded_field_count",
                "kanken_measurement_rows",
            )
        )
        if not has_data:
            return {"trace_id": trace_id, "error": "NOT_FOUND"}
        return out
    except Exception as exc:  # noqa: BLE001
        return {"trace_id": trace_id, "error": str(exc)}
    finally:
        try:
            conn_or_err.close()
        except Exception:  # noqa: BLE001
            pass


def fetch_silver_vb_by_machine(
    vb_machine_no: str,
    user_ctx: Optional[UserContext] = None,
) -> list[dict[str, Any]]:
    """``silver_vb`` から机番一致の judge 等（Graph + SQL 二段デモ）。"""
    from solomon.tools._trino_client import trino_connection_for_user

    cfg = get_trino_config()
    if cfg is None:
        return []

    raw = vb_machine_no.strip().replace("'", "''")
    stripped = raw.lstrip("0") or "0"
    table = _fq("silver_vb")
    sql = f"""
SELECT object_key,
       vb_machine_no,
       trace_id,
       json_extract_scalar(payload, '$.judge') AS judge,
       json_extract_scalar(payload, '$.JUDGE') AS judge_upper,
       ingested_at
FROM {table}
WHERE vb_machine_no = '{raw}'
   OR vb_machine_no = '{stripped}'
   OR vb_machine_no LIKE '%{stripped}'
ORDER BY ingested_at DESC
LIMIT 20
"""
    conn_or_err = trino_connection_for_user(
        user_ctx,
        catalog=silver_catalog_name(),
        schema=silver_schema_name(),
    )
    if isinstance(conn_or_err, dict):
        return []
    try:
        cur = conn_or_err.cursor()
        cur.execute(sql)
        if not cur.description:
            return []
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=False)) for row in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []
    finally:
        try:
            conn_or_err.close()
        except Exception:  # noqa: BLE001
            pass


def fetch_ingest_files_for_trace(
    trace_id: str,
    user_ctx: Optional[UserContext] = None,
) -> list[dict[str, Any]]:
    """``ingest_file_state`` から trace_id に紐づく取込済みソースファイル一覧。"""
    from solomon.tools._trino_client import trino_connection_for_user

    cfg = get_trino_config()
    if cfg is None:
        return []

    tid = trace_id.replace("'", "''")
    table = _fq("ingest_file_state")
    sql = f"""
SELECT object_key, format, trace_id, vb_machine_no, ingested_at
FROM {table}
WHERE trace_id = '{tid}'
ORDER BY format, object_key
LIMIT 50
"""
    conn_or_err = trino_connection_for_user(
        user_ctx,
        catalog=silver_catalog_name(),
        schema=silver_schema_name(),
    )
    if isinstance(conn_or_err, dict):
        return []
    try:
        cur = conn_or_err.cursor()
        cur.execute(sql)
        if not cur.description:
            return []
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=False)) for row in cur.fetchall()]
    except Exception:  # noqa: BLE001
        return []
    finally:
        try:
            conn_or_err.close()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "silver_schema_name",
    "silver_catalog_name",
    "fetch_trace_summary_from_silver",
    "fetch_silver_vb_by_machine",
    "fetch_ingest_files_for_trace",
]
