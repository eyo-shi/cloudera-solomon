"""生成後セルフチェック（scenario 期待値）。

Q1〜Q7 の正解がデータから導けることを、エージェントが書くはずの SQL と同じ形で確かめる。
"""

from __future__ import annotations

from typing import Any

import duckdb
import pandas as pd

UPSTREAM_TRACE = """
    WITH RECURSIVE trace(lot, depth) AS (
        SELECT parent_lot_id, 1 FROM lot_genealogy WHERE child_lot_id IN ({roots})
        UNION ALL
        SELECT g.parent_lot_id, t.depth + 1
        FROM lot_genealogy g JOIN trace t ON g.child_lot_id = t.lot
        WHERE t.depth < 10
    )
"""


def incident_mold_lots(con: duckdb.DuckDBPyConnection, scenario: dict[str, Any]) -> list[str]:
    """D-07 不調期間に M-07 で成形したロット（Q5 の答え）。"""
    h4 = scenario["hidden_facts"]["H4"]
    start, end = h4["window"]
    rows = con.execute(
        """
        SELECT lot_id FROM lots
        WHERE lot_type = 'MOLD' AND equipment_id = ?
          AND CAST(prod_date AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY lot_id
        """,
        [h4["machine"], start, end],
    ).fetchall()
    return [str(r[0]) for r in rows]


def downstream(con: duckdb.DuckDBPyConnection, roots: list[str]) -> pd.DataFrame:
    """roots の下流ロット（lots 付き、DISTINCT）。"""
    quoted = ", ".join(f"'{r}'" for r in roots)
    sql = UPSTREAM_TRACE.format(roots=quoted) + """
        SELECT DISTINCT l.lot_id, l.lot_type, l.part_no
        FROM trace t JOIN lots l ON l.lot_id = t.lot
    """
    return con.execute(sql).df()


def shipped_by_model(con: duckdb.DuckDBPyConnection, unit_lots: list[str]) -> dict[str, int]:
    if not unit_lots:
        return {}
    quoted = ", ".join(f"'{u}'" for u in unit_lots)
    rows = con.execute(
        f"SELECT model_code, sum(qty) FROM shipments WHERE unit_lot_id IN ({quoted}) GROUP BY 1 ORDER BY 1"
    ).fetchall()
    return {str(m): int(q) for m, q in rows}


def connect(frames: dict[str, pd.DataFrame]) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for name, df in frames.items():
        if name.startswith("_") or df is None or df.empty:
            continue
        con.register(name, df)
    return con


def run_checks(frames: dict[str, pd.DataFrame], scenario: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {"ok": True, "checks": []}

    def record(name: str, ok: bool, detail: str = "") -> None:
        results["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            results["ok"] = False

    exp = scenario["expected_answers"]
    cont = scenario["containment"]
    con = connect(frames)

    # --- Q1 ---
    q1 = exp["Q1"]["unit_lots"]
    claims = con.execute(
        "SELECT unit_lot_id, count(*) FROM field_claims WHERE model_code = 'SX-5' GROUP BY 1 ORDER BY 1"
    ).fetchall()
    record("Q1_claim_count", sum(int(c) for _, c in claims) == scenario["incident"]["claim"]["count"], f"claims={claims}")
    record("Q1_unit_lots", sorted(str(u) for u, _ in claims) == sorted(q1), f"units={[u for u, _ in claims]}")
    dates = con.execute(
        f"SELECT CAST(prod_date AS VARCHAR) FROM unit_lots WHERE lot_id IN ({', '.join(repr(u) for u in q1)}) ORDER BY 1"
    ).fetchall()
    record("Q1_prod_dates", [d[0] for d in dates] == exp["Q1"]["prod_dates"], f"dates={dates}")
    bad_vin = con.execute(
        """
        SELECT count(*) FROM field_claims c
        WHERE NOT EXISTS (
            SELECT 1 FROM shipments s
            WHERE s.unit_lot_id = c.unit_lot_id AND s.model_code = c.model_code
              AND c.vin BETWEEN s.vin_from AND s.vin_to
        )
        """
    ).fetchone()[0]
    record("claims_vin_in_shipment_range", bad_vin == 0, f"outside={bad_vin}")

    # --- Q2（117 由来）---
    q2 = exp["Q2"]
    resin = q2["resin_lot"]
    d117 = downstream(con, [resin])
    molds117 = d117[d117["lot_type"] == "MOLD"]
    record("Q2_mold_lots", len(molds117) == q2["mold_lots"], f"mold={len(molds117)}")
    units117 = sorted(d117[d117["lot_type"] == "UNIT"]["lot_id"].tolist())
    products = sorted(set(d117[d117["lot_type"] == "UNIT"]["part_no"]))
    record("Q2_products", products == sorted(q2["products"]), f"products={products}")
    ship117 = shipped_by_model(con, units117)
    record("Q2_models", sorted(ship117) == sorted(q2["models"]), f"models={ship117}")
    record("Q2_units", sum(ship117.values()) == q2["units"], f"units={sum(ship117.values())}")
    oems = con.execute(
        f"SELECT count(DISTINCT oem_id) FROM shipments WHERE unit_lot_id IN ({', '.join(repr(u) for u in units117)})"
    ).fetchone()[0]
    record("Q2_oems", oems == q2["oems"], f"oems={oems}")

    fixed3 = con.execute(
        f"""
        SELECT DISTINCT s.model_code
        FROM lot_genealogy g1
        JOIN lot_genealogy g2 ON g2.child_lot_id = g1.parent_lot_id
        JOIN lot_genealogy g3 ON g3.child_lot_id = g2.parent_lot_id
        JOIN shipments s ON s.unit_lot_id = g3.parent_lot_id
        WHERE g1.child_lot_id = '{resin}'
        """
    ).fetchall()
    record("fixed_3hop_only_sx5", [r[0] for r in fixed3] == ["SX-5"], f"models={fixed3}")

    # --- Q3 / H2 ---
    defect = con.execute(
        "SELECT defect_code FROM defects WHERE note LIKE '%QR-2024-0815%'"
    ).fetchall()
    record("H2_defect_code", [d[0] for d in defect] == [exp["Q3"]["defect_code_zero"]], f"codes={defect}")

    # --- Q4 / H5 ---
    incident = incident_mold_lots(con, scenario)
    h5 = scenario["hidden_facts"]["H5"]
    bl = con.execute(
        f"""
        SELECT lot_id IN ({', '.join(repr(x) for x in incident) or "''"}) AS incident,
               avg(value / usl) * 100 AS pct, count(*) AS n,
               sum(CASE WHEN judgment <> 'OK' THEN 1 ELSE 0 END) AS ng
        FROM inspection_results i
        WHERE item = 'バックラッシ'
          AND lot_id IN (SELECT lot_id FROM lots WHERE lot_type = 'MOLD' AND plant = '豊浜工場')
        GROUP BY 1
        """
    ).fetchall()
    by = {bool(r[0]): (float(r[1]), int(r[2]), int(r[3])) for r in bl}
    inc = by.get(True)
    record("H5_backlash_incident", inc is not None and abs(inc[0] - h5["backlash_avg_pct_usl_incident"]) <= 2, f"{inc}")
    nor = by.get(False)
    if nor is not None:
        record("H5_backlash_normal", abs(nor[0] - h5["backlash_avg_pct_usl_normal"]) <= 5, f"{nor}")
    ng = con.execute("SELECT count(*) FROM inspection_results WHERE judgment <> 'OK'").fetchone()[0]
    record("inspection_all_ok", ng == 0, f"ng={ng}")

    # --- Q5 / H4 ---
    record("Q5_mold_lots", len(incident) == exp["Q5"]["mold_lots"], f"mold={len(incident)}")
    mats = con.execute(
        f"""
        SELECT DISTINCT g.child_lot_id FROM lot_genealogy g
        WHERE g.parent_lot_id IN ({', '.join(repr(x) for x in incident)})
        ORDER BY 1
        """
    ).fetchall()
    m = scenario["incident"]["material_lots"]
    record("Q5_material_lots", [r[0] for r in mats] == sorted([m["primary"], m["secondary"]]), f"materials={mats}")

    # --- Q6 ---
    dall = downstream(con, incident)
    n_sub = int((dall["lot_type"] == "SUBASSY").sum())
    units_all = sorted(dall[dall["lot_type"] == "UNIT"]["lot_id"].tolist())
    record("Q6_subassy_lots", n_sub == cont["subassy_lots"], f"subassy={n_sub}")
    record("Q6_unit_lots", len(units_all) == cont["unit_lots"], f"units={len(units_all)}")
    ship_all = shipped_by_model(con, units_all)
    expected_ship = {model: qty for per_oem in cont["shipped"].values() for model, qty in per_oem.items()}
    record("Q6_shipped", ship_all == expected_ship, f"shipped={ship_all}")
    scope = incident + dall["lot_id"].tolist()
    inv = con.execute(
        f"SELECT tier, sum(qty) FROM inventory WHERE lot_id IN ({', '.join(repr(x) for x in scope)}) GROUP BY 1 ORDER BY 1"
    ).fetchall()
    inv_map = {int(t): int(q) for t, q in inv}
    record(
        "Q6_inventory",
        inv_map.get(1) == cont["inventory_tier1"] and inv_map.get(2) == cont["inventory_tier2"],
        f"inventory={inv_map}",
    )

    # --- Q7 ---
    q7 = scenario["q7_ppap"]
    alt = con.execute(
        """
        SELECT a.part_no, a.ppap_status
        FROM supplier_alternatives a
        JOIN suppliers s1 ON s1.supplier_id = a.supplier_id
        JOIN suppliers s2 ON s2.supplier_id = a.alt_supplier_id
        WHERE a.material_part_no = ? AND s1.name = '北陸ケミカル' AND s2.name = '東洋ポリマー'
        ORDER BY 1
        """,
        [q7["material"]],
    ).fetchall()
    approved = sorted(p for p, s in alt if s == "APPROVED")
    pending = sorted(p for p, s in alt if s == "PENDING")
    record("Q7_parts", len(alt) == exp["Q7"]["parts"], f"parts={alt}")
    record("Q7_approved", approved == sorted(q7["approved_parts"]), f"approved={approved}")
    record("Q7_pending", pending == sorted(q7["pending_parts"]), f"pending={pending}")
    pa66 = con.execute(
        "SELECT count(*) FROM parts WHERE material_spec = ? AND category = '成形品'", [q7["material"]]
    ).fetchone()[0]
    record("Q7_parts_material_spec", pa66 == q7["parts_using_north_chem"], f"parts={pa66}")

    # --- 文書 ---
    if "doc_index" in frames and not frames["doc_index"].empty:
        ids = set(frames["doc_index"]["doc_id"].astype(str))
        planted = [d["doc_id"] for d in scenario.get("planted_documents") or []]
        record("planted_docs", all(p in ids for p in planted), f"missing={[p for p in planted if p not in ids]}")

    return results
