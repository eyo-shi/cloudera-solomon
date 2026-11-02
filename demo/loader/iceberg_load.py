"""Parquet → S3 → Trino Iceberg。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable

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


def load_table_method_b(
    spec: TableSpec,
    parquet: Path,
    *,
    dry_run: bool,
    recreate: bool,
    execute_fn: Callable[[str], None],
    batch_size: int = 1000,
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
    df = df[cols]
    n = len(df)
    if dry_run:
        print(f"  -- insert {n} rows into {fq} (method B, batches of {batch_size})")
        return n
    col_list = ", ".join(cols)
    for start in range(0, n, batch_size):
        batch = df.iloc[start : start + batch_size]
        values_parts = []
        for _, row in batch.iterrows():
            vals = []
            for v in row:
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    vals.append("NULL")
                elif isinstance(v, str):
                    vals.append("'" + v.replace("'", "''") + "'")
                else:
                    vals.append(str(v))
            values_parts.append("(" + ", ".join(vals) + ")")
        sql = f"INSERT INTO {fq} ({col_list}) VALUES " + ", ".join(values_parts)
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
    for stmt in re.split(r";\s*\n", text):
        stmt = stmt.strip()
        if stmt and not stmt.startswith("--"):
            trino_execute(stmt, dry_run=dry_run, execute_fn=execute_fn)


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
    use_a = method == "a"
    if method is None and query_fn:
        use_a = detect_hive_catalog(query_fn)
    method_used = "a" if use_a else "b"

    loaded: dict[str, int] = {}
    for name, spec in domain.tables.items():
        if spec.kind in ("document_index",) and not parquets.get(name):
            continue
        if spec.kind == "graph_only" and name not in parquets:
            continue
        pq_path = parquets.get(name)
        if pq_path is None:
            continue
        local_count = parquet_row_count(pq_path)
        if not recreate and query_fn:
            try:
                existing = query_fn(f"SELECT count(*) FROM {spec.fq}")
                if existing and int(existing[0][0]) == local_count:
                    print(f"skip {spec.fq} ({local_count} rows)")
                    loaded[name] = local_count
                    continue
                if existing and int(existing[0][0]) != local_count:
                    print(
                        f"WARN {spec.fq}: table has {existing[0][0]} rows, "
                        f"parquet has {local_count}"
                    )
            except Exception:  # noqa: BLE001
                pass
        s3_uri = f"{demo_s3_prefix(domain.domain_name)}/{spec.table}"
        upload_parquet_to_s3(pq_path, s3_uri, dry_run=dry_run, upload_fn=upload_fn)
        if method_used == "a":
            loaded[name] = load_table_method_a(
                spec,
                pq_path,
                s3_uri,
                hive_catalog=hive_cat,
                stage_schema=stage_schema,
                dry_run=dry_run,
                recreate=recreate,
                execute_fn=execute_fn or (lambda _s: None),
            )
        else:
            loaded[name] = load_table_method_b(
                spec,
                pq_path,
                dry_run=dry_run,
                recreate=recreate,
                execute_fn=execute_fn or (lambda _s: None),
            )
        exp = manifest_counts.get(name)
        if exp is not None and exp != loaded[name]:
            print(f"WARN manifest count {name}: expected {exp}, loaded {loaded[name]}")

    run_derived_sql(domain.domain_dir, dry_run=dry_run, execute_fn=execute_fn or (lambda _s: None))
    return {"method": method_used, "tables": loaded}
