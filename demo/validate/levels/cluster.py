"""Cluster level: Trino / Bolt / OpenSearch (+ domain plugin)."""

from __future__ import annotations

from pathlib import Path

from demo.validate.model import CheckResult
from demo.validate.plugins import call_plugin, load_domain_plugin
from demo.validate.scenario import load_scenario, search_check_defs
from demo.validate.search_checks import run_search_checks


def run_cluster(domain_dir: Path) -> tuple[list[CheckResult], list[dict], str]:
    scenario = load_scenario(domain_dir)
    results: list[CheckResult] = []

    plugin = load_domain_plugin(domain_dir)
    for cr in call_plugin(plugin, "run_cluster", domain_dir, scenario):
        if isinstance(cr, CheckResult):
            results.append(cr)
        elif isinstance(cr, dict):
            results.append(
                CheckResult(
                    name=str(cr.get("name", "plugin")),
                    ok=bool(cr.get("ok")),
                    detail=str(cr.get("detail") or ""),
                    category="cluster",
                )
            )

    use_os = _opensearch_configured()
    sc_results, rows, md = run_search_checks(search_check_defs(scenario), use_opensearch=use_os)
    results.extend(sc_results)

    return results, rows, md


def _opensearch_configured() -> bool:
    try:
        from solomon.transport.config import get_opensearch_config

        return get_opensearch_config() is not None
    except Exception:  # noqa: BLE001
        return False


__all__ = ["run_cluster"]
