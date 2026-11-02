"""生成後セルフチェック（scenario 期待値）。"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd


def run_checks(frames: dict[str, pd.DataFrame], scenario: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {"ok": True, "checks": []}

    def record(name: str, ok: bool, detail: str = "") -> None:
        results["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            results["ok"] = False

    exp = scenario["expected_answers"]
    unit = frames["unit_lots"]
    q1_lots = set(exp["Q1"]["unit_lots"])
    found = set(unit["lot_id"].astype(str).tolist())
    record("Q1_unit_lots", q1_lots <= found, f"missing {q1_lots - found}")

    claims = frames["field_claims"]
    sx5 = claims[claims["model_code"] == "SX-5"]
    record("Q1_claim_count", len(sx5) >= 14, f"count={len(sx5)}")

    mat = frames["material_lots"]
    record("H1_material_lot", "HC-2605-117" in set(mat["lot_id"]), "")

    mold = frames["lots"]
    mold_m07 = mold[(mold["lot_type"] == "MOLD") & (mold["equipment_id"] == "M-07")]
    record("Q5_mold_lots_min", len(mold_m07) >= 15, f"mold={len(mold_m07)}")

    insp = frames["inspection_results"]
    bl = insp[insp["item"] == "バックラッシ"]
    if len(bl):
        incident = bl[bl["lot_id"].astype(str).str.startswith("ML-")]
        if len(incident):
            ratio = (incident["value"] / incident["usl"]).mean() * 100
            record("H5_backlash_incident", ratio > 85, f"ratio={ratio:.1f}%")
        normal = bl[~bl["lot_id"].astype(str).str.startswith("ML-")]
        if len(normal):
            ratio_n = (normal["value"] / normal["usl"]).mean() * 100
            record("H5_backlash_normal", ratio_n < 75, f"ratio={ratio_n:.1f}%")

    docs = frames.get("doc_index", pd.DataFrame())
    if len(docs):
        planted = docs[docs["doc_id"] == "QR-2024-0815"]
        record("H2_8d_doc", len(planted) == 1, "")

    # DuckDB schema parity
    con = duckdb.connect()
    for name, df in frames.items():
        if name.startswith("_") or df.empty:
            continue
        con.register("t", df)
        con.execute("SELECT count(*) FROM t").fetchone()
    record("duckdb_load", True, "")

    return results
