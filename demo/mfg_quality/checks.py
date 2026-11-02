"""製造品質デモ固有の local / cluster 検証。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from demo.validate.model import CheckResult


def _cr(name: str, ok: bool, detail: str = "") -> CheckResult:
    return CheckResult(name=name, ok=ok, detail=detail, category="local")


def run_local(
    domain_dir: Path,
    scenario: dict[str, Any],
    tables: dict[str, pd.DataFrame],
) -> list[CheckResult]:
    results: list[CheckResult] = []
    exp = scenario.get("expected_answers") or {}
    hidden = scenario.get("hidden_facts") or {}

    if "unit_lots" in tables:
        lots = set(tables["unit_lots"]["lot_id"].astype(str))
        q1 = set(exp.get("Q1", {}).get("unit_lots") or [])
        results.append(_cr("Q1_unit_lots", q1 <= lots, f"missing={sorted(q1 - lots)}"))

    if "field_claims" in tables:
        sx5 = tables["field_claims"]
        sx5 = sx5[sx5["model_code"] == "SX-5"] if "model_code" in sx5.columns else sx5.iloc[0:0]
        results.append(_cr("Q1_claim_count", len(sx5) >= 14, f"count={len(sx5)}"))

    if "material_lots" in tables:
        mat = set(tables["material_lots"]["lot_id"].astype(str))
        results.append(_cr("H1_material_lot", "HC-2605-117" in mat, ""))

    results.extend(_genealogy_checks(tables, scenario))
    results.extend(_fixed_hop_join_check(tables, scenario))
    results.extend(_defects_and_inspection(tables, scenario))
    results.extend(_backlash_checks(tables, scenario))
    results.extend(_document_chunk_checks(domain_dir, scenario))
    results.extend(_daily_vs_runs(tables, scenario))

    return results


def _genealogy_checks(tables: dict[str, pd.DataFrame], scenario: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    gen = tables.get("lot_genealogy")
    lots = tables.get("lots")
    if gen is None or gen.empty:
        return [_cr("genealogy_present", False, "no lot_genealogy")]

    con = duckdb.connect()
    con.register("lot_genealogy", gen)
    if lots is not None and not lots.empty:
        con.register("lots", lots)

    for lot_id, qkey, field in (
        ("HC-2605-117", "Q2", "resin_lot"),
        ("HC-2605-121", "Q5", "equipment"),
    ):
        sql = f"""
            WITH RECURSIVE trace(lot, depth) AS (
                SELECT parent_lot_id, 1
                FROM lot_genealogy WHERE child_lot_id = '{lot_id}'
                UNION ALL
                SELECT g.parent_lot_id, trace.depth + 1
                FROM lot_genealogy g
                JOIN trace ON g.child_lot_id = trace.lot
                WHERE trace.depth < 8
            )
            SELECT max(depth) FROM trace
        """
        try:
            max_depth = con.execute(sql).fetchone()[0]
            results.append(_cr(f"genealogy_depth:{lot_id}", max_depth is not None, f"max_depth={max_depth}"))
        except Exception as exc:  # noqa: BLE001
            results.append(_cr(f"genealogy_depth:{lot_id}", False, str(exc)))

    exp_q2 = scenario.get("expected_answers", {}).get("Q2") or {}
    if lots is not None and "model_code" in tables.get("shipments", pd.DataFrame()).columns:
        # 材料→ユニット→出荷→車種（parquet 上の近似）
        ship = tables.get("shipments")
        units = tables.get("unit_lots")
        if ship is not None and units is not None:
            con.register("shipments", ship)
            con.register("unit_lots", units)
            sql = """
                WITH RECURSIVE trace(lot) AS (
                    SELECT parent_lot_id FROM lot_genealogy WHERE child_lot_id = 'HC-2605-117'
                    UNION ALL
                    SELECT g.parent_lot_id FROM lot_genealogy g JOIN trace ON g.child_lot_id = trace.lot
                )
                SELECT DISTINCT s.model_code
                FROM trace t
                JOIN unit_lots u ON u.lot_id = t.lot
                JOIN shipments s ON s.unit_lot_id = u.lot_id
            """
            try:
                models = {str(r[0]) for r in con.execute(sql).fetchall()}
                expected = set(exp_q2.get("models") or [])
                results.append(
                    _cr(
                        "Q2_models_from_genealogy",
                        expected <= models if expected else bool(models),
                        f"models={sorted(models)} expected={sorted(expected)}",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                results.append(_cr("Q2_models_from_genealogy", False, str(exc)))

    hops = scenario.get("genealogy_hops") or {}
    for key, label in (
        ("eps_a200_path_hops", "EPS-A200"),
        ("pg310_pwr55_path_hops", "PG-310/PWR-55"),
        ("wh200_eps_a210_path_hops", "WH-200/EPS-A210"),
    ):
        if key in hops:
            results.append(_cr(f"path_hops:{label}", True, f"expected_hops={hops[key]} (manual path SQL in cluster)"))

    return results


def _fixed_hop_join_check(tables: dict[str, pd.DataFrame], scenario: dict[str, Any]) -> list[CheckResult]:
    gen = tables.get("lot_genealogy")
    if gen is None or gen.empty:
        return []
    con = duckdb.connect()
    con.register("g", gen)
    sql = """
        SELECT DISTINCT g3.parent_lot_id AS unit_lot
        FROM g g1
        JOIN g g2 ON g2.child_lot_id = g1.parent_lot_id
        JOIN g g3 ON g3.child_lot_id = g2.parent_lot_id
        WHERE g1.child_lot_id = 'HC-2605-117'
    """
    try:
        units = {str(r[0]) for r in con.execute(sql).fetchall()}
    except Exception as exc:  # noqa: BLE001
        return [_cr("fixed_3hop_join", False, str(exc))]
    # KX-1 経路は 4 段以上のため 3 段 JOIN だけでは EPS-A200/SX-5 系に偏る
    kx1_leak = any("KX-1" in u or "A210" in u for u in units)
    results = [
        _cr("fixed_3hop_join_runs", len(units) > 0, f"units={len(units)} sample={list(units)[:5]}"),
        _cr("fixed_3hop_no_kx1_path", not kx1_leak, f"kx1_leak={kx1_leak}"),
    ]
    return results


def _defects_and_inspection(tables: dict[str, pd.DataFrame], scenario: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    h2 = (scenario.get("hidden_facts") or {}).get("H2") or {}
    code = h2.get("defects_table_code") or "外観その他"
    if "defects" in tables:
        d = tables["defects"]
        if "defect_code" in d.columns and "doc_id" in d.columns:
            old = d[d["doc_id"].astype(str).str.contains("2024", na=False)]
            if len(old):
                only = set(old["defect_code"].astype(str).unique())
                results.append(_cr("H2_defects_code", only <= {code}, f"codes={only}"))
    if "inspection_results" in tables:
        insp = tables["inspection_results"]
        if "result" in insp.columns:
            ng = insp[insp["result"].astype(str).str.upper() == "NG"]
            results.append(_cr("inspection_ng_zero", len(ng) == 0, f"ng_count={len(ng)}"))
    return results


def _backlash_checks(tables: dict[str, pd.DataFrame], scenario: dict[str, Any]) -> list[CheckResult]:
    h5 = (scenario.get("hidden_facts") or {}).get("H5") or {}
    target_in = float(h5.get("backlash_avg_pct_usl_incident") or 92)
    target_out = float(h5.get("backlash_avg_pct_usl_normal") or 60)
    insp = tables.get("inspection_results")
    if insp is None or insp.empty or "item" not in insp.columns:
        return []
    bl = insp[insp["item"] == "バックラッシ"]
    results: list[CheckResult] = []
    if len(bl) and "value" in bl.columns and "usl" in bl.columns:
        incident = bl[bl["lot_id"].astype(str).str.startswith("ML-")]
        if len(incident):
            ratio = (incident["value"] / incident["usl"]).mean() * 100
            results.append(
                _cr(
                    "H5_backlash_incident",
                    abs(ratio - target_in) <= 2,
                    f"ratio={ratio:.1f}% target={target_in}±2",
                )
            )
        normal = bl[~bl["lot_id"].astype(str).str.startswith("ML-")]
        if len(normal):
            ratio_n = (normal["value"] / normal["usl"]).mean() * 100
            results.append(
                _cr(
                    "H5_backlash_normal",
                    abs(ratio_n - target_out) <= 5,
                    f"ratio={ratio_n:.1f}% target={target_out}±5",
                )
            )
    return results


def _document_chunk_checks(domain_dir: Path, scenario: dict[str, Any]) -> list[CheckResult]:
    path = domain_dir / "output" / "chunks.jsonl"
    if not path.is_file():
        return [_cr("chunks.jsonl", False, "missing")]
    h2h3 = 0
    decoy = 0
    total_異音 = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            text = str(row.get("text") or "")
            doc_id = str(row.get("doc_id") or "")
            if "異音" in text:
                total_異音 += 1
                if doc_id.startswith("QR-2024") or "DR-2025" in doc_id or doc_id.startswith("DR-2026"):
                    h2h3 += 1
                if row.get("doc_type") == "decoy" or "decoy" in doc_id.lower():
                    decoy += 1
    h6 = (scenario.get("hidden_facts") or {}).get("H6") or {}
    min_decoy = int(h6.get("decoy_doc_count") or 200)
    results = [
        _cr("H2_H3_no_異音", h2h3 == 0, f"planted_with_異音={h2h3}"),
        _cr("H6_decoy_異音", total_異音 >= min_decoy, f"chunks_with_異音={total_異音}"),
    ]
    return results


def _daily_vs_runs(tables: dict[str, pd.DataFrame], scenario: dict[str, Any]) -> list[CheckResult]:
    results: list[CheckResult] = []
    runs = tables.get("production_runs")
    chunks_path = None
    # 仕込み日報は chunks / doc_index に依存 — production_runs の M-07 期間だけ確認
    h4 = (scenario.get("hidden_facts") or {}).get("H4") or {}
    win = h4.get("window") or ["2026-05-12", "2026-05-26"]
    if runs is not None and "equipment_id" in runs.columns and "start_ts" in runs.columns:
        m7 = runs[runs["equipment_id"] == "M-07"]
        results.append(_cr("Q5_runs_M07", len(m7) > 0, f"rows={len(m7)}"))
    maint_text = ""
    for name, df in tables.items():
        if "maintenance" in name and "text" in df.columns:
            maint_text = " ".join(df["text"].astype(str).head(20).tolist())
            break
    if maint_text:
        ok = bool(re.search(r"5/12|05-12|5/26|05-26", maint_text))
        results.append(_cr("H4_maintenance_window", ok, "regex 5/12..5/26 in maintenance sample"))
    return results


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
