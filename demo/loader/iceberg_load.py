"""Parquet → S3 → Trino Iceberg。"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from demo.loader.ossie_domain import DomainModel, TableSpec
from demo.loader.trino_types import create_table_ddl


def demo_s3_prefix(domain_name: str) -> str:
    base = (os.environ.get("DEMO_S3_PREFIX") or "s3://demo-data").rstrip("/")
    return f"{base}/{domain_name}"


def parquet_row_count(path: Path) -> int:
    if not path.is_file():
        return 0
    return pq.read_metadata(path).num_rows


def list_parquet_tables(output_dir: Path) -> dict[str, Path]:
    tables_dir = output_dir / "tables"
    out: dict[str, Path] = {}
    if not tables_dir.is_dir():
        return out
    for p in sorted(tables_dir.glob("*.parquet")):
        out[p.stem] = p
    return out


def upload_parquet_to_s3(
    local: Path,
    s3_uri: str,
    *,
    dry_run: bool,
    upload_fn: Callable[[Path, str], None] | None = None,
) -> None:
    if dry_run:
        print(f"  upload {local} -> {s3_uri}/")
        return
    if upload_fn:
        upload_fn(local, s3_uri)
        return
    from solomon.tools._s3_client import parse_s3_uri, s3_client_for_user

    bucket, prefix = parse_s3_uri(s3_uri if s3_uri.endswith("/") else s3_uri + "/")
    client = s3_client_for_user(None)
    key_prefix = prefix.rstrip("/") + "/"
    client.upload_file(str(local), bucket, key_prefix + local.name)


def trino_execute(sql: str, *, dry_run: bool, execute_fn: Callable[[str], None] | None) -> None:
    if dry_run:
        print(sql.rstrip() + ";\n")
        return
    if execute_fn:
        execute_fn(sql)
        return
    raise RuntimeError("trino execute_fn required when not dry-run")


def detect_hive_catalog(execute_scalar: Callable[[str], Any]) -> bool:
    try:
        rows = execute_scalar("SHOW CATALOGS")
        if isinstance(rows, list):
            names = {str(r[0]).lower() for r in rows}
            return "hive" in names
    except Exception:  # noqa: BLE001
        return False
    return False


DEFAULT_INSERT_MAX_BYTES = 256 * 1024
DEFAULT_INSERT_MAX_ROWS = 1000


def insert_max_bytes() -> int:
    """方式 B の INSERT 1 文あたりの SQL 上限 bytes (``DEMO_TRINO_INSERT_MAX_BYTES``)。

    Trino の前段 (ゲートウェイ / プロキシ) に本文サイズ上限がある場合は小さくする。
    """
    raw = (os.environ.get("DEMO_TRINO_INSERT_MAX_BYTES") or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_INSERT_MAX_BYTES
    except ValueError:
        value = DEFAULT_INSERT_MAX_BYTES
    return max(1024, value)


def _is_null(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, (list, tuple, dict, np.ndarray)):
        return False
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _plain_number(v: Any) -> str:
    """指数表記を使わない数値リテラル (Trino では小数点付きは DECIMAL リテラル)。"""
    from decimal import Decimal

    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    return format(Decimal(str(v)), "f")


def sql_literal(v: Any, trino_type: str) -> str:
    """Python 値 → 列の Trino 型に合う SQL リテラル。"""
    if _is_null(v):
        return "NULL"
    t = trino_type.strip().lower()
    if t.startswith("array("):
        inner = t[len("array(") : -1]
        items = list(v) if not isinstance(v, str) else [v]
        if not items:
            return f"CAST(ARRAY[] AS {t})"
        return "ARRAY[" + ", ".join(sql_literal(x, inner) for x in items) + "]"
    if t == "date":
        return "DATE " + _quote(pd.Timestamp(v).strftime("%Y-%m-%d"))
    if t.startswith("timestamp"):
        ts = pd.Timestamp(v)
        return "TIMESTAMP " + _quote(ts.strftime("%Y-%m-%d %H:%M:%S.%f"))
    if t == "boolean":
        if isinstance(v, str):
            return "true" if v.strip().lower() in ("true", "1", "yes", "y", "t") else "false"
        return "true" if bool(v) else "false"
    if t in ("bigint", "integer", "smallint", "tinyint"):
        return str(int(v))
    if t.startswith("decimal") or t in ("double", "real"):
        if isinstance(v, str):
            v = float(v)
        if isinstance(v, float) and not math.isfinite(v):
            return "NULL"
        return _plain_number(v)
    return _quote(str(v))


def insert_statements(
    fq: str,
    fields: list[Any],
    rows: list[tuple[Any, ...]],
    *,
    max_bytes: int,
    max_rows: int = DEFAULT_INSERT_MAX_ROWS,
) -> list[str]:
    """``INSERT ... VALUES`` を SQL 長 ``max_bytes`` / ``max_rows`` 行ごとに分割する。"""
    from demo.loader.trino_types import trino_type

    types = [trino_type(f) for f in fields]
    head = f"INSERT INTO {fq} ({', '.join(f.name for f in fields)}) VALUES "
    head_len = len(head.encode("utf-8"))
    statements: list[str] = []
    batch: list[str] = []
    size = head_len
    for row in rows:
        tup = "(" + ", ".join(sql_literal(v, t) for v, t in zip(row, types)) + ")"
        tup_len = len(tup.encode("utf-8")) + 2
        if batch and (size + tup_len > max_bytes or len(batch) >= max_rows):
            statements.append(head + ", ".join(batch))
            batch, size = [], head_len
        batch.append(tup)
        size += tup_len
    if batch:
        statements.append(head + ", ".join(batch))
    return statements


def load_table_method_b(
    spec: TableSpec,
    parquet: Path,
    *,
    dry_run: bool,
    recreate: bool,
    execute_fn: Callable[[str], None],
    max_bytes: int | None = None,
) -> int:
    fq = spec.fq
    if recreate:
        trino_execute(f"DROP TABLE IF EXISTS {fq}", dry_run=dry_run, execute_fn=execute_fn)
    trino_execute(create_table_ddl(fq, spec.fields), dry_run=dry_run, execute_fn=execute_fn)
    df = pd.read_parquet(parquet)
    if df.empty:
        return 0
    cols = [f.name for f in spec.fields]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    # 列ごとに tolist() すると numpy 型が Python 型になり、行方向の型昇格も起きない
    rows = list(zip(*(df[c].tolist() for c in cols)))
    statements = insert_statements(
        fq, spec.fields, rows, max_bytes=max_bytes or insert_max_bytes()
    )
    n = len(rows)
    if dry_run:
        print(f"  -- insert {n} rows into {fq} (method B, {len(statements)} statements)")
        print("  -- " + statements[0][:300] + (" ..." if len(statements[0]) > 300 else ""))
        return n
    for sql in statements:
        execute_fn(sql)
    return n


def load_table_method_a(
    spec: TableSpec,
    parquet: Path,
    s3_uri: str,
    *,
    hive_catalog: str,
    stage_schema: str,
    dry_run: bool,
    recreate: bool,
    execute_fn: Callable[[str], None],
) -> int:
    fq = spec.fq
    stage_table = f"{hive_catalog}.{stage_schema}.{spec.table}_stage"
    if recreate:
        trino_execute(f"DROP TABLE IF EXISTS {fq}", dry_run=dry_run, execute_fn=execute_fn)
    ext_loc = s3_uri.rstrip("/") + "/"
    trino_execute(f"DROP TABLE IF EXISTS {stage_table}", dry_run=dry_run, execute_fn=execute_fn)
    trino_execute(
        f"CREATE TABLE {stage_table} ({', '.join(f'{f.name} varchar' for f in spec.fields)}) "
        f"WITH (external_location = '{ext_loc}', format = 'PARQUET')",
        dry_run=dry_run,
        execute_fn=execute_fn,
    )
    trino_execute(
        f"CREATE TABLE {fq} WITH (format = 'PARQUET') AS SELECT * FROM {stage_table}",
        dry_run=dry_run,
        execute_fn=execute_fn,
    )
    trino_execute(f"DROP TABLE {stage_table}", dry_run=dry_run, execute_fn=execute_fn)
    return parquet_row_count(parquet)


def run_derived_sql(
    domain_dir: Path,
    *,
    dry_run: bool,
    execute_fn: Callable[[str], None],
) -> None:
    path = domain_dir / "derived.sql"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    for chunk in re.split(r";\s*\n", text):
        # 先頭のコメント行だけを落とす (コメントで始まる文を丸ごと捨てない)
        lines = chunk.strip().splitlines()
        while lines and (not lines[0].strip() or lines[0].lstrip().startswith("--")):
            lines.pop(0)
        stmt = "\n".join(lines).strip().rstrip(";").strip()
        if stmt:
            trino_execute(stmt, dry_run=dry_run, execute_fn=execute_fn)


def select_method(method: str | None, query_fn: Callable[[str], Any] | None) -> str:
    """``--iceberg-method`` 未指定時の方式。

    方式 A は hive カタログに加えて Parquet の置き場 (``DEMO_S3_PREFIX``) が要るので、
    両方そろうときだけ自動選択する。それ以外 (CDW Trino 等) は方式 B (INSERT)。
    """
    if method in ("a", "b"):
        return method
    if not (os.environ.get("DEMO_S3_PREFIX") or "").strip():
        return "b"
    if query_fn and detect_hive_catalog(query_fn):
        return "a"
    return "b"


def ensure_schemas(
    specs: list[TableSpec],
    *,
    dry_run: bool,
    execute_fn: Callable[[str], None],
) -> list[str]:
    """投入先の ``catalog.schema`` を ``CREATE SCHEMA IF NOT EXISTS`` で作る。

    ``DEMO_ICEBERG_SCHEMA_LOCATION`` (例 ``s3a://bucket/warehouse``) を指定すると
    ``<location>/<schema>.db`` を schema の location にする (既定は metastore の warehouse)。
    """
    location_base = (os.environ.get("DEMO_ICEBERG_SCHEMA_LOCATION") or "").strip().rstrip("/")
    created: list[str] = []
    for spec in specs:
        fq_schema = f"{spec.catalog}.{spec.schema}"
        if fq_schema in created:
            continue
        sql = f"CREATE SCHEMA IF NOT EXISTS {fq_schema}"
        if location_base:
            sql += f" WITH (location = '{location_base}/{spec.schema}.db')"
        trino_execute(sql, dry_run=dry_run, execute_fn=execute_fn)
        created.append(fq_schema)
    return created


def _existing_row_count(query_fn: Callable[[str], Any], fq: str) -> int | None:
    """既存表の行数。表が無い / 読めないときは None。"""
    try:
        rows = query_fn(f"SELECT count(*) FROM {fq}")
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    return int(rows[0][0])


def load_iceberg(
    domain: DomainModel,
    *,
    dry_run: bool,
    recreate: bool,
    method: str | None,
    execute_fn: Callable[[str], None] | None = None,
    query_fn: Callable[[str], Any] | None = None,
    upload_fn: Callable[[Path, str], None] | None = None,
) -> dict[str, Any]:
    output = domain.domain_dir / "output"
    parquets = list_parquet_tables(output)
    manifest_counts: dict[str, int] = {}
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        import json

        manifest_counts = json.loads(manifest_path.read_text()).get("table_counts") or {}

    hive_cat = os.environ.get("DEMO_HIVE_CATALOG", "hive")
    stage_schema = os.environ.get("DEMO_STAGE_SCHEMA", "default")
    method_used = select_method(method, query_fn)
    print(f"iceberg method: {method_used}")

    targets: list[tuple[str, TableSpec, Path]] = []
    for name, spec in domain.tables.items():
        pq_path = parquets.get(name)
        if pq_path is None:
            continue
        targets.append((name, spec, pq_path))

    if not targets:
        msg = (
            f"no parquet tables for this domain under {output / 'tables'} "
            "(output/ は Git 管理外。先に生成する: "
            f"PYTHONPATH=. python -m demo.{domain.domain_name}.generator --seed 42 --scale 1.0 --docs template)"
        )
        if not dry_run:
            raise RuntimeError(msg)
        print(f"WARN {msg}")

    ensure_schemas(
        [spec for _, spec, _ in targets],
        dry_run=dry_run,
        execute_fn=execute_fn or (lambda _s: None),
    )

    loaded: dict[str, int] = {}
    for name, spec, pq_path in targets:
        local_count = parquet_row_count(pq_path)
        table_recreate = recreate
        if not recreate and query_fn:
            existing_count = _existing_row_count(query_fn, spec.fq)
            if existing_count == local_count:
                print(f"skip {spec.fq} ({local_count} rows)")
                loaded[name] = local_count
                continue
            if existing_count is not None:
                # 途中で失敗した INSERT の残り等。追記すると重複するので作り直す
                print(
                    f"WARN {spec.fq}: table has {existing_count} rows, "
                    f"parquet has {local_count} -> recreate"
                )
                table_recreate = True
        print(f"load {spec.fq} ({local_count} rows)")
        if method_used == "a":
            s3_uri = f"{demo_s3_prefix(domain.domain_name)}/{spec.table}"
            upload_parquet_to_s3(pq_path, s3_uri, dry_run=dry_run, upload_fn=upload_fn)
            loaded[name] = load_table_method_a(
                spec,
                pq_path,
                s3_uri,
                hive_catalog=hive_cat,
                stage_schema=stage_schema,
                dry_run=dry_run,
                recreate=table_recreate,
                execute_fn=execute_fn or (lambda _s: None),
            )
        else:
            loaded[name] = load_table_method_b(
                spec,
                pq_path,
                dry_run=dry_run,
                recreate=table_recreate,
                execute_fn=execute_fn or (lambda _s: None),
            )
        exp = manifest_counts.get(name)
        if exp is not None and exp != loaded[name]:
            print(f"WARN manifest count {name}: expected {exp}, loaded {loaded[name]}")

    run_derived_sql(domain.domain_dir, dry_run=dry_run, execute_fn=execute_fn or (lambda _s: None))
    return {"method": method_used, "tables": loaded}
