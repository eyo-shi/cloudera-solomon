"""Local level: parquet / chunks on disk (+ domain plugin)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from demo.loader.iceberg_load import list_parquet_tables
from demo.validate.fk_checks import check_foreign_keys
from demo.validate.model import CheckResult
from demo.validate.plugins import call_plugin, load_domain_plugin
from demo.validate.scenario import load_scenario


def _load_tables(domain_dir: Path) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {}
    for name, path in list_parquet_tables(domain_dir / "output").items():
        tables[name] = pd.read_parquet(path)
    return tables


def run_local(domain_dir: Path) -> list[CheckResult]:
    scenario = load_scenario(domain_dir)
    results: list[CheckResult] = []
    tables = _load_tables(domain_dir)
    if not tables:
        results.append(
            CheckResult(name="local_data", ok=False, detail="no parquet under output/tables", category="local")
        )
        return results

    results.extend(check_foreign_keys(domain_dir, tables))

    plugin = load_domain_plugin(domain_dir)
    for cr in call_plugin(plugin, "run_local", domain_dir, scenario, tables):
        if isinstance(cr, CheckResult):
            results.append(cr)
        elif isinstance(cr, dict):
            results.append(
                CheckResult(
                    name=str(cr.get("name", "plugin")),
                    ok=bool(cr.get("ok")),
                    detail=str(cr.get("detail") or ""),
                    category="local",
                )
            )

    return results


__all__ = ["run_local"]
