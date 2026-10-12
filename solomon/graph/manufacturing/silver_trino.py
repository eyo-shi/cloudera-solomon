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


def _multi_row_query(conn: Any, sql: str) -> list[dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(sql)
    if not cur.description:
        return []
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=False)) for row in cur.fetchall()]


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


def fetch_kanken_measurements_for_trace(
    trace_id: str,
    filter_terms: list[str],
    user_ctx: Optional[UserContext] = None,
) -> dict[str, Any]:
    """``silver_kanken_fields`` から完検測定行（シンボル / 初検）を取得。"""
    from solomon.tools._trino_client import trino_connection_for_user

    cfg = get_trino_config()
    if cfg is None:
        return {"trace_id": trace_id, "error": "TRINO_NOT_CONFIGURED"}

    tid = trace_id.replace("'", "''")
    table = _fq("silver_kanken_fields")
    terms = [t.strip() for t in filter_terms if t and t.strip()]
    if not terms:
        terms = ["TRQ", "EOP"]

    like_clauses: list[str] = []
    for term in terms:
        esc = term.replace("'", "''")
        like_clauses.append(
            f"(LOWER(symbol_name) LIKE LOWER('%{esc}%') "
            f"OR LOWER(step_name) LIKE LOWER('%{esc}%'))"
        )
    where_filter = " OR ".join(like_clauses)
    payload_likes: list[str] = []
    for term in terms:
        esc = term.replace("'", "''")
        payload_likes.append(
            f"LOWER(json_extract_scalar(payload, '$.symbol_name')) LIKE LOWER('%{esc}%')"
        )
    payload_filter = " OR ".join(payload_likes)

    sql_variants = (
        f"""
SELECT step_name, symbol_name, unit, spec_lower, spec_upper,
       first_value, j_reinspect, object_key
FROM {table}
WHERE trace_id = '{tid}'
  AND ({where_filter})
ORDER BY step_name, symbol_name
LIMIT 80
""",
        f"""
SELECT
  json_extract_scalar(payload, '$.step_name') AS step_name,
  json_extract_scalar(payload, '$.symbol_name') AS symbol_name,
  json_extract_scalar(payload, '$.unit') AS unit,
  json_extract_scalar(payload, '$.spec_lower') AS spec_lower,
  json_extract_scalar(payload, '$.spec_upper') AS spec_upper,
  json_extract_scalar(payload, '$.first_value') AS first_value,
  json_extract_scalar(payload, '$.j_reinspect') AS j_reinspect,
  object_key
FROM {table}
WHERE trace_id = '{tid}'
  AND ({payload_filter})
ORDER BY 1, 2
LIMIT 80
""",
    )

    conn_or_err = trino_connection_for_user(
        user_ctx,
        catalog=silver_catalog_name(),
        schema=silver_schema_name(),
    )
    if isinstance(conn_or_err, dict):
        return {"trace_id": trace_id, "error": conn_or_err.get("message", "TRINO_FAILED")}

    last_error: str | None = None
    try:
        for sql in sql_variants:
            try:
                rows = _multi_row_query(conn_or_err, sql)
                return {
                    "trace_id": trace_id,
                    "source": "lakehouse",
                    "silver_schema": silver_schema_name(),
                    "filter_terms": terms,
                    "rows": rows,
                }
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return {"trace_id": trace_id, "error": last_error or "QUERY_FAILED"}
    finally:
        try:
            conn_or_err.close()
        except Exception:  # noqa: BLE001
            pass


def fetch_kanken_representative_measurements(
    trace_id: str,
    limit: int = 3,
    user_ctx: Optional[UserContext] = None,
) -> dict[str, Any]:
    """``silver_kanken_fields`` から代表測定行を先頭 N 件取得（Q12）。"""
    from solomon.tools._trino_client import trino_connection_for_user

    cfg = get_trino_config()
    if cfg is None:
        return {"trace_id": trace_id, "error": "TRINO_NOT_CONFIGURED"}

    lim = max(1, min(int(limit), 20))
    tid = trace_id.replace("'", "''")
    table = _fq("silver_kanken_fields")
    schema = silver_schema_name()
    sql_variants = (
        f"""
SELECT step_name, symbol_name, unit, first_value, object_key
FROM {table}
WHERE trace_id = '{tid}'
ORDER BY step_name, symbol_name
LIMIT {lim}
""",
        f"""
SELECT
  json_extract_scalar(payload, '$.step_name') AS step_name,
  json_extract_scalar(payload, '$.symbol_name') AS symbol_name,
  json_extract_scalar(payload, '$.unit') AS unit,
  json_extract_scalar(payload, '$.first_value') AS first_value,
  object_key
FROM {table}
WHERE trace_id = '{tid}'
ORDER BY 1, 2
LIMIT {lim}
""",
    )

    conn_or_err = trino_connection_for_user(
        user_ctx,
        catalog=silver_catalog_name(),
        schema=schema,
    )
    if isinstance(conn_or_err, dict):
        return {"trace_id": trace_id, "error": conn_or_err.get("message", "TRINO_FAILED")}

    last_error: str | None = None
    try:
        for sql in sql_variants:
            try:
                rows = _multi_row_query(conn_or_err, sql)
                return {
                    "trace_id": trace_id,
                    "source": "lakehouse",
                    "silver_schema": schema,
                    "limit": lim,
                    "rows": rows,
                }
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return {"trace_id": trace_id, "error": last_error or "QUERY_FAILED"}
    finally:
        try:
            conn_or_err.close()
        except Exception:  # noqa: BLE001
            pass


def fetch_id_fields_by_judge(
    trace_id: str,
    *,
    data_format: str = "j5_main_id",
    value_judge: str = "未検",
    user_ctx: Optional[UserContext] = None,
) -> dict[str, Any]:
    """``silver_id_fields`` — T447 解釈済み ID 項目（判定フィルタ）。"""
    from solomon.tools._trino_client import trino_connection_for_user

    cfg = get_trino_config()
    if cfg is None:
        return {"trace_id": trace_id, "error": "TRINO_NOT_CONFIGURED"}

    tid = trace_id.replace("'", "''")
    fmt = data_format.replace("'", "''")
    judge = value_judge.replace("'", "''")
    table = _fq("silver_id_fields")

    sql_variants = (
        f"""
SELECT
  COALESCE(field_name, label, info, info_content) AS field_name,
  address_hex,
  value_judge,
  value,
  process_name,
  timing_band,
  format,
  object_key
FROM {table}
WHERE trace_id = '{tid}'
  AND format = '{fmt}'
  AND value_judge = '{judge}'
ORDER BY field_name, address_hex
LIMIT 120
""",
        f"""
SELECT
  COALESCE(field_name, label, info, info_content) AS field_name,
  address_hex,
  value_judge,
  value,
  process_name,
  timing_band,
  format,
  object_key
FROM {table}
WHERE trace_id = '{tid}'
  AND timing_band = 'main_out'
  AND value_judge = '{judge}'
ORDER BY field_name, address_hex
LIMIT 120
""",
        f"""
SELECT
  COALESCE(
    json_extract_scalar(payload, '$.field_name'),
    json_extract_scalar(payload, '$.label'),
    json_extract_scalar(payload, '$.info')
  ) AS field_name,
  json_extract_scalar(payload, '$.address_hex') AS address_hex,
  json_extract_scalar(payload, '$.value_judge') AS value_judge,
  json_extract_scalar(payload, '$.value') AS value,
  json_extract_scalar(payload, '$.process_name') AS process_name,
  timing_band,
  format,
  object_key
FROM {table}
WHERE trace_id = '{tid}'
  AND (
    format = '{fmt}'
    OR timing_band = 'main_out'
  )
  AND COALESCE(
    value_judge,
    json_extract_scalar(payload, '$.value_judge')
  ) = '{judge}'
ORDER BY 1, 2
LIMIT 120
""",
    )

    conn_or_err = trino_connection_for_user(
        user_ctx,
        catalog=silver_catalog_name(),
        schema=silver_schema_name(),
    )
    if isinstance(conn_or_err, dict):
        return {"trace_id": trace_id, "error": conn_or_err.get("message", "TRINO_FAILED")}

    last_error: str | None = None
    try:
        for sql in sql_variants:
            try:
                rows = _multi_row_query(conn_or_err, sql)
                return {
                    "trace_id": trace_id,
                    "source": "lakehouse",
                    "silver_schema": silver_schema_name(),
                    "data_format": data_format,
                    "value_judge": value_judge,
                    "rows": rows,
                }
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return {"trace_id": trace_id, "error": last_error or "QUERY_FAILED"}
    finally:
        try:
            conn_or_err.close()
        except Exception:  # noqa: BLE001
            pass


def fetch_silver_vb_ng_tests(
    *,
    judge: str = "NG",
    limit: int = 80,
    user_ctx: Optional[UserContext] = None,
) -> dict[str, Any]:
    """``silver_vb`` で総合判定 NG（等）の VB 試験行 + ``silver_vb_steps`` 件数。"""
    from solomon.tools._trino_client import trino_connection_for_user

    cfg = get_trino_config()
    if cfg is None:
        return {"error": "TRINO_NOT_CONFIGURED"}

    lim = max(1, min(int(limit), 200))
    j = judge.strip().replace("'", "''").upper()
    vb_table = _fq("silver_vb")
    steps_table = _fq("silver_vb_steps")
    schema = silver_schema_name()
    sql_variants = (
        f"""
SELECT
  v.object_key,
  v.vb_machine_no,
  v.ingested_at,
  COALESCE(
    TRY_CAST(json_extract_scalar(v.payload, '$.static_step_count') AS INTEGER),
    sc.step_cnt
  ) AS step_count,
  COALESCE(
    json_extract_scalar(v.payload, '$.test_datetime'),
    json_extract_scalar(v.payload, '$.passed_at'),
    json_extract_scalar(v.payload, '$.test_date'),
    CAST(v.ingested_at AS VARCHAR)
  ) AS test_datetime,
  COALESCE(
    json_extract_scalar(v.payload, '$.judge'),
    json_extract_scalar(v.payload, '$.JUDGE')
  ) AS judge
FROM {vb_table} v
LEFT JOIN (
  SELECT object_key, etag, COUNT(*) AS step_cnt
  FROM {steps_table}
  GROUP BY object_key, etag
) sc ON v.object_key = sc.object_key AND v.etag = sc.etag
WHERE UPPER(COALESCE(
    json_extract_scalar(v.payload, '$.judge'),
    json_extract_scalar(v.payload, '$.JUDGE'),
    ''
  )) = '{j}'
ORDER BY v.vb_machine_no, v.ingested_at DESC
LIMIT {lim}
""",
        f"""
SELECT
  v.object_key,
  v.vb_machine_no,
  v.ingested_at,
  COALESCE(
    TRY_CAST(json_extract_scalar(v.payload, '$.static_step_count') AS INTEGER),
    sc.step_cnt
  ) AS step_count,
  COALESCE(
    json_extract_scalar(v.payload, '$.test_datetime'),
    json_extract_scalar(v.payload, '$.passed_at'),
    CAST(v.ingested_at AS VARCHAR)
  ) AS test_datetime,
  COALESCE(
    json_extract_scalar(v.payload, '$.judge'),
    json_extract_scalar(v.payload, '$.JUDGE')
  ) AS judge
FROM {vb_table} v
LEFT JOIN (
  SELECT object_key, COUNT(*) AS step_cnt
  FROM {steps_table}
  GROUP BY object_key
) sc ON v.object_key = sc.object_key
WHERE UPPER(COALESCE(
    json_extract_scalar(v.payload, '$.judge'),
    json_extract_scalar(v.payload, '$.JUDGE'),
    ''
  )) = '{j}'
ORDER BY v.vb_machine_no, v.ingested_at DESC
LIMIT {lim}
""",
    )

    conn_or_err = trino_connection_for_user(
        user_ctx,
        catalog=silver_catalog_name(),
        schema=schema,
    )
    if isinstance(conn_or_err, dict):
        return {"error": conn_or_err.get("message") or "TRINO_CONNECTION_FAILED"}

    last_error: str | None = None
    try:
        for sql in sql_variants:
            try:
                rows = _multi_row_query(conn_or_err, sql)
                normalized: list[dict[str, Any]] = []
                for row in rows:
                    key = str(row.get("object_key") or "").strip()
                    if not key:
                        continue
                    step_raw = row.get("step_count")
                    step_count: int | None
                    try:
                        step_count = int(step_raw) if step_raw is not None else None
                    except (TypeError, ValueError):
                        step_count = None
                    normalized.append(
                        {
                            "object_key": key,
                            "vb_machine_no": str(row.get("vb_machine_no") or "—"),
                            "step_count": step_count,
                            "test_datetime": str(row.get("test_datetime") or "—"),
                            "judge": str(row.get("judge") or j),
                            "ingested_at": row.get("ingested_at"),
                        }
                    )
                return {
                    "source": "lakehouse",
                    "silver_schema": schema,
                    "judge_filter": judge,
                    "rows": normalized,
                    "reference_sql": sql.strip(),
                }
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return {"error": last_error or "QUERY_FAILED", "silver_schema": schema}
    finally:
        try:
            conn_or_err.close()
        except Exception:  # noqa: BLE001
            pass


def fetch_kiban_with_shukken_and_kanken(
    limit: int = 5,
    user_ctx: Optional[UserContext] = None,
) -> dict[str, Any]:
    """``ingest_file_state`` を trace_id × format で集計し、出検+完検両方ある KIBAN を返す。"""
    from solomon.tools._trino_client import trino_connection_for_user

    cfg = get_trino_config()
    if cfg is None:
        return {"error": "TRINO_NOT_CONFIGURED"}

    lim = max(1, min(int(limit), 50))
    table = _fq("ingest_file_state")
    schema = silver_schema_name()
    sql = f"""
SELECT trace_id,
  COUNT(CASE WHEN format = 'j5_shukken_id' THEN 1 END) AS shukken_cnt,
  COUNT(CASE WHEN format IN ('kanken', 'j5_kanken') THEN 1 END) AS kanken_cnt,
  COUNT(CASE WHEN format = 'j5_shukken_id' THEN 1 END)
    + COUNT(CASE WHEN format IN ('kanken', 'j5_kanken') THEN 1 END) AS total_cnt
FROM {table}
WHERE trace_id IS NOT NULL AND TRIM(CAST(trace_id AS VARCHAR)) <> ''
GROUP BY trace_id
HAVING COUNT(CASE WHEN format = 'j5_shukken_id' THEN 1 END) > 0
   AND COUNT(CASE WHEN format IN ('kanken', 'j5_kanken') THEN 1 END) > 0
ORDER BY total_cnt DESC, trace_id
LIMIT {lim}
"""

    conn_or_err = trino_connection_for_user(
        user_ctx,
        catalog=silver_catalog_name(),
        schema=schema,
    )
    if isinstance(conn_or_err, dict):
        return {"error": conn_or_err.get("message") or "TRINO_CONNECTION_FAILED"}

    try:
        rows = _multi_row_query(conn_or_err, sql)
        normalized: list[dict[str, Any]] = []
        for row in rows:
            tid = str(row.get("trace_id") or "").strip()
            if not tid:
                continue
            shukken = int(row.get("shukken_cnt") or 0)
            kanken = int(row.get("kanken_cnt") or 0)
            total = int(row.get("total_cnt") or shukken + kanken)
            normalized.append(
                {
                    "trace_id": tid,
                    "shukken_cnt": shukken,
                    "kanken_cnt": kanken,
                    "total_cnt": total,
                }
            )
        return {
            "source": "lakehouse",
            "silver_schema": schema,
            "limit": lim,
            "rows": normalized,
            "reference_sql": sql.strip(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "silver_schema": schema}
    finally:
        try:
            conn_or_err.close()
        except Exception:  # noqa: BLE001
            pass


_ID_DUMP_ALT_KIBAN_LINK = "id_dump_alt_kiban"


def fetch_id_dump_alt_kiban_links(
    trace_id: str,
    user_ctx: Optional[UserContext] = None,
) -> dict[str, Any]:
    """メインID hex 内の別 KIBAN 候補 — ``silver_trace_links``（``id_dump_alt_kiban``）。"""
    from solomon.tools._trino_client import trino_connection_for_user

    cfg = get_trino_config()
    if cfg is None:
        return {"trace_id": trace_id, "error": "TRINO_NOT_CONFIGURED"}

    tid = trace_id.replace("'", "''")
    table = _fq("silver_trace_links")
    schema = silver_schema_name()
    link = _ID_DUMP_ALT_KIBAN_LINK.replace("'", "''")
    sql_variants = (
        f"""
SELECT trace_id, vb_machine_no, link_type, confidence, detail,
       source_object_key, object_key, ingested_at
FROM {table}
WHERE trace_id = '{tid}'
  AND link_type = '{link}'
ORDER BY ingested_at DESC
LIMIT 30
""",
        f"""
SELECT trace_id, vb_machine_no, link_type, confidence, detail,
       source_object_key, object_key, ingested_at
FROM {table}
WHERE trace_id = '{tid}'
  AND link_type LIKE '%alt%kiban%'
ORDER BY ingested_at DESC
LIMIT 30
""",
    )

    conn_or_err = trino_connection_for_user(
        user_ctx,
        catalog=silver_catalog_name(),
        schema=schema,
    )
    if isinstance(conn_or_err, dict):
        return {
            "trace_id": trace_id,
            "error": conn_or_err.get("message") or "TRINO_CONNECTION_FAILED",
        }

    last_error: str | None = None
    try:
        for sql in sql_variants:
            try:
                rows = _multi_row_query(conn_or_err, sql)
                return {
                    "trace_id": trace_id,
                    "source": "lakehouse",
                    "silver_schema": schema,
                    "link_type": _ID_DUMP_ALT_KIBAN_LINK,
                    "rows": rows,
                    "reference_sql": sql.strip(),
                }
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return {"trace_id": trace_id, "error": last_error or "QUERY_FAILED"}
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
    "fetch_kanken_measurements_for_trace",
    "fetch_kanken_representative_measurements",
    "fetch_id_fields_by_judge",
    "fetch_kiban_with_shukken_and_kanken",
    "fetch_silver_vb_ng_tests",
    "fetch_id_dump_alt_kiban_links",
]
