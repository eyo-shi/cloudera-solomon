"""Relationship FK checks via DuckDB over parquet tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml

from demo.validate.model import CheckResult


def _load_relationships(semantic_root: Path) -> list[dict[str, Any]]:
    models_dir = semantic_root / "models"
    rels: list[dict[str, Any]] = []
    for path in sorted(models_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        for rel in raw.get("relationships") or []:
            if isinstance(rel, dict):
                rels.append(rel)
    return rels


def check_foreign_keys(domain_dir: Path, tables: dict[str, pd.DataFrame]) -> list[CheckResult]:
    rels = _load_relationships(domain_dir / "semantic")
    results: list[CheckResult] = []
    con = duckdb.connect()
    for rel in rels:
        fr = rel.get("from")
        to = rel.get("to")
        fcols = rel.get("from_columns") or []
        tcols = rel.get("to_columns") or []
        if not fr or not to or not fcols or not tcols:
            continue
        if fr not in tables or to not in tables:
            continue
        left = tables[fr]
        right = tables[to]
        if left.empty or right.empty:
            continue
        con.register("l", left)
        con.register("r", right)
        join = " AND ".join(f"l.{fc} = r.{tc}" for fc, tc in zip(fcols, tcols, strict=False))
        sql = f"""
            SELECT count(*) FROM l
            WHERE l.{fcols[0]} IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM r WHERE {join})
        """
        try:
            orphans = int(con.execute(sql).fetchone()[0])
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(
                    name=f"fk:{rel.get('name', fr)}",
                    ok=False,
                    detail=str(exc),
                    category="local",
                )
            )
            continue
        ok = orphans == 0
        results.append(
            CheckResult(
                name=f"fk:{rel.get('name', fr)}->{to}",
                ok=ok,
                detail=f"orphan rows={orphans}",
                category="local",
            )
        )
    return results


__all__ = ["check_foreign_keys"]
