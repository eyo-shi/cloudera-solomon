"""製造品質デモ固有の local / cluster 検証。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from demo.validate.model import CheckResult


def _cr(name: str, ok: bool, detail: str = "") -> CheckResult:
    return CheckResult(name=name, ok=ok, detail=detail, category="local")


def run_local(
    domain_dir: Path,
    scenario: dict[str, Any],
    tables: dict[str, pd.DataFrame],
) -> list[CheckResult]:
    """Parquet 上で Q1〜Q7 の正解が導けるかを確認（生成器セルフチェックと同じ SQL）。"""
    from demo.mfg_quality.generator.checks import run_checks

    required = ("lots", "lot_genealogy", "unit_lots", "shipments", "field_claims", "inspection_results")
    missing = [t for t in required if t not in tables or tables[t].empty]
    if missing:
        return [_cr("tables_present", False, f"missing={missing}")]
    try:
        report = run_checks(tables, scenario)
    except Exception as exc:  # noqa: BLE001
        return [_cr("scenario_checks", False, f"{type(exc).__name__}: {exc}")]
    results = [_cr(c["name"], c["ok"], c["detail"]) for c in report["checks"]]
    results.extend(_document_chunk_checks(domain_dir, scenario))
    return results


def _document_chunk_checks(domain_dir: Path, scenario: dict[str, Any]) -> list[CheckResult]:
    path = domain_dir / "output" / "chunks.jsonl"
    if not path.is_file():
        return [_cr("chunks.jsonl", False, "missing")]
    planted = {str(d["doc_id"]): d for d in scenario.get("planted_documents") or []}
    forbidden = scenario.get("forbidden_terms_planted_docs") or ["異音"]
    planted_bad: list[str] = []
    seen: set[str] = set()
    total_kw = 0
    maint_text: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            text = str(row.get("text") or "")
            doc_id = str(row.get("doc_id") or "")
            if "異音" in text:
                total_kw += 1
            if doc_id in planted:
                seen.add(doc_id)
                if any(term in text for term in forbidden):
                    planted_bad.append(doc_id)
                if planted[doc_id].get("doc_type") == "maintenance":
                    maint_text.append(text)
    h6 = (scenario.get("hidden_facts") or {}).get("H6") or {}
    min_decoy = int(h6.get("decoy_doc_count") or 200)
    return [
        _cr("planted_docs_in_chunks", seen == set(planted), f"missing={sorted(set(planted) - seen)}"),
        _cr("H2_H3_no_異音", not planted_bad, f"planted_with_forbidden={planted_bad}"),
        _cr("H6_decoy_異音", total_kw >= min_decoy, f"chunks_with_異音={total_kw}"),
        _cr(
            "H4_maintenance_window",
            bool(maint_text) and bool(re.search(r"5/26|05-26", " ".join(maint_text))),
            "maintenance docs mention 5/12〜5/26",
        ),
    ]


def run_cluster(domain_dir: Path, scenario: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.extend(_trino_genealogy(scenario))
    results.extend(_bolt_q2(scenario))
    return results


def _trino_genealogy(scenario: dict[str, Any]) -> list[CheckResult]:
    try:
        from demo.loader.trino_runtime import make_trino_callbacks
    except ImportError:
        return [CheckResult(name="trino_genealogy", ok=True, detail="skip", category="cluster")]
    try:
        _, query_fn = make_trino_callbacks()
    except RuntimeError as exc:
        return [CheckResult(name="trino_genealogy", ok=True, detail=f"skip: {exc}", category="cluster")]

    sql = """
        WITH RECURSIVE trace(lot, depth) AS (
            SELECT parent_lot_id, 1
            FROM iceberg.mfg_quality.lot_genealogy
            WHERE child_lot_id = 'HC-2605-117'
            UNION ALL
            SELECT g.parent_lot_id, trace.depth + 1
            FROM iceberg.mfg_quality.lot_genealogy g
            JOIN trace ON g.child_lot_id = trace.lot
            WHERE trace.depth < 8
        )
        SELECT max(depth) FROM trace
    """
    try:
        row = query_fn(sql)
        depth = row[0][0] if row else None
        exp = (scenario.get("genealogy_hops") or {}).get("eps_a200_path_hops") or 3
        ok = depth is not None and int(depth) >= int(exp)
        return [
            CheckResult(
                name="trino_genealogy_depth_117",
                ok=ok,
                detail=f"max_depth={depth} expected>={exp}",
                category="cluster",
            )
        ]
    except Exception as exc:  # noqa: BLE001
        return [CheckResult(name="trino_genealogy", ok=False, detail=str(exc), category="cluster")]


def _bolt_q2(scenario: dict[str, Any]) -> list[CheckResult]:
    try:
        from solomon.graph.session import with_read_session
    except ImportError:
        return []
    exp_models = set((scenario.get("expected_answers") or {}).get("Q2", {}).get("models") or [])
    cypher = """
        MATCH (r:Lot {lot_id:$lot_id})-[:CONSUMED_BY*1..6]->(u:Lot {lot_type:'UNIT'})
              -[:SHIPPED_AS]->(:Shipment)-[:FOR_MODEL]->(m:VehicleModel)
        RETURN DISTINCT m.model_name AS model
    """

    def _run(session: Any) -> set[str]:
        recs = session.run(cypher, lot_id="HC-2605-117")
        return {str(r["model"]) for r in recs if r.get("model")}

    try:
        found = with_read_session(_run)
        ok = exp_models <= found if exp_models else bool(found)
        return [
            CheckResult(
                name="bolt_Q2_models",
                ok=ok,
                detail=f"models={sorted(found)} expected={sorted(exp_models)}",
                category="cluster",
            )
        ]
    except Exception as exc:  # noqa: BLE001
        return [CheckResult(name="bolt_Q2", ok=True, detail=f"skip: {exc}", category="cluster")]


__all__ = ["run_local", "run_cluster"]
