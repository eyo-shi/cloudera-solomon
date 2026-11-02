"""Parquet column sets vs Ossie fields."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from demo.loader.ossie_domain import DomainModel, load_domain
from demo.loader.iceberg_load import list_parquet_tables
from demo.validate.model import CheckResult


def check_parquet_vs_ossie(domain_dir: Path, *, validate_semantic: bool = False) -> list[CheckResult]:
    domain = load_domain(domain_dir, validate=validate_semantic)
    parquets = list_parquet_tables(domain_dir / "output")
    results: list[CheckResult] = []
    for name, spec in domain.tables.items():
        if spec.kind in ("document_index",):
            continue
        path = parquets.get(name)
        if path is None:
            continue
        schema_cols = set(pq.read_schema(path).names)
        field_cols = {f.name for f in spec.fields}
        missing_in_pq = field_cols - schema_cols
        extra_in_pq = schema_cols - field_cols
        ok = not missing_in_pq
        detail = ""
        if missing_in_pq:
            detail = f"missing columns in parquet: {sorted(missing_in_pq)}"
        elif extra_in_pq:
            detail = f"extra columns (ok): {sorted(extra_in_pq)[:8]}"
        else:
            detail = f"{len(field_cols)} columns match"
        results.append(
            CheckResult(
                name=f"parquet_fields:{name}",
                ok=ok,
                detail=detail,
                category="semantic",
            )
        )
    if not results and not parquets:
        results.append(
            CheckResult(
                name="parquet_fields",
                ok=True,
                detail="no parquet tables (skip)",
                category="semantic",
            )
        )
    return results


__all__ = ["check_parquet_vs_ossie"]
