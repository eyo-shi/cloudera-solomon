"""scenario.yaml の事件データを固定 ID で注入。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd


def _empty_frames(schemas: dict[str, list]) -> dict[str, pd.DataFrame]:
    return {name: pd.DataFrame(columns=[c["name"] for c in cols]) for name, cols in schemas.items()}


def inject_scenario(scenario: dict[str, Any], schemas: dict[str, list]) -> dict[str, pd.DataFrame]:
    """事件・隠し事実の行を構築（背景は simulate が埋める）。"""
    frames = _empty_frames(schemas)
    inc = scenario["incident"]
    exp = scenario["expected_answers"]

    oems = pd.DataFrame(
        [
            {"oem_id": "OEM-MIRAI", "name": "ミライ自動車"},
            {"oem_id": "OEM-YAMATO", "name": "大和モータース"},
            {"oem_id": "OEM-BG", "name": "背景 OEM"},
        ]
    )
    models = pd.DataFrame(
        [
            {"model_code": "SX-5", "model_name": "SX-5", "oem_id": "OEM-MIRAI", "sop_date": date(2024, 1, 1)},
            {"model_code": "CV-3", "model_name": "CV-3", "oem_id": "OEM-MIRAI", "sop_date": date(2024, 6, 1)},
            {"model_code": "KX-1", "model_name": "KX-1", "oem_id": "OEM-MIRAI", "sop_date": date(2025, 1, 1)},
            {"model_code": "VN-7", "model_name": "VN-7", "oem_id": "OEM-YAMATO", "sop_date": date(2023, 1, 1)},
        ]
    )
    suppliers = pd.DataFrame(
        [
            {"supplier_id": "SUP-T1", "name": "東邦精機株式会社", "tier": 1, "country": "JP", "plant": "豊浜工場"},
            {"supplier_id": "SUP-T2", "name": "三協モールド工業", "tier": 2, "country": "JP", "plant": "豊浜工場"},
            {"supplier_id": "SUP-NC", "name": "北陸ケミカル", "tier": 3, "country": "JP", "plant": "-"},
            {"supplier_id": "SUP-TP", "name": "東洋ポリマー", "tier": 3, "country": "JP", "plant": "-"},
        ]
    )
    parts = pd.DataFrame(
        [
            {"part_no": "WH-200", "name": "ウォームホイール", "category": "成形品", "material_spec": "PA66-GF30", "supplier_id": "SUP-T2"},
            {"part_no": "PG-310", "name": "PW ギア", "category": "成形品", "material_spec": "PA66-GF30", "supplier_id": "SUP-T2"},
            {"part_no": "EPS-A200", "name": "EPS ユニット", "category": "ユニット", "material_spec": "-", "supplier_id": "SUP-T1"},
            {"part_no": "EPS-A210", "name": "EPS ユニット派生", "category": "ユニット", "material_spec": "-", "supplier_id": "SUP-T1"},
            {"part_no": "PWR-55", "name": "レギュレータ", "category": "ユニット", "material_spec": "-", "supplier_id": "SUP-T1"},
            {"part_no": "PA66-GF30", "name": "樹脂ペレット", "category": "材料", "material_spec": "PA66-GF30", "supplier_id": "SUP-NC"},
        ]
    )
    equipment = pd.DataFrame(
        [
            {"equipment_id": "M-07", "name": "成形機 7 号", "type": "成形機", "plant": "豊浜工場", "parent_equipment_id": None},
            {"equipment_id": "D-07", "name": "ホッパードライヤー 7", "type": "乾燥機", "plant": "豊浜工場", "parent_equipment_id": "M-07"},
        ]
    )
    equipment_links = pd.DataFrame(
        [{"edge_id": "EL-D07-M07", "equipment_id": "D-07", "parent_equipment_id": "M-07"}]
    )

    material_lots = pd.DataFrame(
        [
            {
                "lot_id": "HC-2605-117",
                "part_no": "PA66-GF30",
                "supplier_id": "SUP-NC",
                "receipt_date": date(2026, 5, 10),
                "qty_kg": 1200,
                "coa_moisture_pct": 0.08,
            },
            {
                "lot_id": "HC-2605-121",
                "part_no": "PA66-GF30",
                "supplier_id": "SUP-NC",
                "receipt_date": date(2026, 5, 18),
                "qty_kg": 800,
                "coa_moisture_pct": 0.07,
            },
        ]
    )

    unit_rows = []
    for row in inc["claim"]["unit_lots"]:
        unit_rows.append(
            {
                "lot_id": row["lot_id"],
                "part_no": "EPS-A200",
                "plant": "豊浜工場",
                "prod_date": date.fromisoformat(row["prod_date"]),
                "qty": 500,
            }
        )
    unit_lots = pd.DataFrame(unit_rows)

    mold_lot_ids: list[str] = []
    for i in range(6):
        mold_lot_ids.append(f"ML-117-WH-{i+1:02d}")
    for i in range(3):
        mold_lot_ids.append(f"ML-117-PG-{i+1:02d}")
    for i in range(6):
        mold_lot_ids.append(f"ML-121-WH-{i+1:02d}")

    genealogy_rows: list[dict[str, Any]] = []
    lots_rows: list[dict[str, Any]] = []

    def add_lot(lot_id: str, lot_type: str, part_no: str, prod: date, eq: str | None, qty: int) -> None:
        lots_rows.append(
            {
                "lot_id": lot_id,
                "lot_type": lot_type,
                "part_no": part_no,
                "plant": "豊浜工場",
                "prod_date": prod,
                "equipment_id": eq,
                "qty": qty,
            }
        )

    add_lot("HC-2605-117", "MATERIAL", "PA66-GF30", date(2026, 5, 10), None, 1)
    add_lot("HC-2605-121", "MATERIAL", "PA66-GF30", date(2026, 5, 18), None, 1)

    edge_seq = 0
    for mid in mold_lot_ids:
        part = "WH-200" if "WH" in mid else "PG-310"
        mat = "HC-2605-117" if "117" in mid else "HC-2605-121"
        prod = date(2026, 5, 14) if "117" in mid else date(2026, 5, 20)
        add_lot(mid, "MOLD", part, prod, "M-07", 1000)
        edge_seq += 1
        genealogy_rows.append(
            {
                "edge_id": f"EG-{edge_seq}",
                "child_lot_id": mat,
                "parent_lot_id": mid,
                "qty_used": 50,
            }
        )

    # EPS-A200 path (3 hops to unit): mold -> sub1 -> sub2 -> unit
    sub_a = "SA-A200-01"
    sub_b = "SA-A200-02"
    add_lot(sub_a, "SUBASSY", "SUB-EPS-1", date(2026, 5, 28), None, 500)
    add_lot(sub_b, "SUBASSY", "SUB-EPS-2", date(2026, 5, 30), None, 500)
    wh_mold = mold_lot_ids[0]
    for child, parent in [
        (wh_mold, sub_a),
        (sub_a, sub_b),
        (sub_b, unit_rows[0]["lot_id"]),  # noqa: unit_lots order
        (sub_b, unit_rows[1]["lot_id"]),
        (sub_b, unit_rows[2]["lot_id"]),
    ]:
        edge_seq += 1
        genealogy_rows.append(
            {"edge_id": f"EG-{edge_seq}", "child_lot_id": child, "parent_lot_id": parent, "qty_used": 1}
        )

    insp_rows = []
    for lot_id in mold_lot_ids + unit_lots["lot_id"].astype(str).tolist():
        usl, lsl = 0.15, 0.05
        pct_usl = 0.92 if lot_id.startswith("ML-") else 0.60
        val = usl * pct_usl
        insp_rows.append(
            {
                "insp_id": f"INSP-{lot_id}-BL",
                "lot_id": lot_id,
                "item": "バックラッシ",
                "value": val,
                "lsl": lsl,
                "usl": usl,
                "judgment": "OK",
            }
        )

    claims = []
    symptoms = [
        "ハンドル操作時ゴトゴト",
        "ステアリングから打音",
        "低速コーナリングでカタカタ",
        "RATTLE noise on turn",
        "NOISE steering",
    ]
    for i in range(14):
        claims.append(
            {
                "claim_id": f"CLM-SX5-2026-{i+1:03d}",
                "oem_id": "OEM-MIRAI",
                "model_code": "SX-5",
                "vin": f"VIN-SX5-{i+1:05d}",
                "unit_lot_id": unit_rows[i % 3]["lot_id"],
                "claim_date": date(2026, 10, 5 + i % 10),
                "symptom_code": "NOISE" if i % 2 == 0 else "RATTLE",
                "symptom_text": symptoms[i % len(symptoms)],
            }
        )

    cont = scenario["containment"]
    shipments = []
    sid = 0
    for oem, models_qty in cont["shipped"].items():
        for model, qty in models_qty.items():
            sid += 1
            shipments.append(
                {
                    "shipment_id": f"SHP-{sid:05d}",
                    "unit_lot_id": unit_rows[0]["lot_id"],
                    "oem_id": oem,
                    "model_code": model,
                    "ship_date": date(2026, 7, 1),
                    "qty": qty,
                    "vin_from": f"V-{model}-001",
                    "vin_to": f"V-{model}-{qty}",
                }
            )

    alt = pd.DataFrame(
        [
            {"material_part_no": "PA66-GF30", "supplier_id": "SUP-NC", "alt_supplier_id": "SUP-TP", "ppap_status": "APPROVED"},
            {"material_part_no": "PG-310", "supplier_id": "SUP-T2", "alt_supplier_id": "SUP-TP", "ppap_status": "PENDING"},
        ]
    )

    runs = pd.DataFrame(
        [
            {
                "run_id": "RUN-M07-0514",
                "equipment_id": "M-07",
                "output_lot_id": mold_lot_ids[0],
                "part_no": "WH-200",
                "start_ts": datetime(2026, 5, 14, 8, 0),
                "end_ts": datetime(2026, 5, 14, 16, 0),
                "qty": 1000,
                "operator_id": "OP-12",
                "shift": "A",
            }
        ]
    )

    frames["oem_customers"] = pd.concat([frames["oem_customers"], oems], ignore_index=True)
    frames["vehicle_models"] = pd.concat([frames["vehicle_models"], models], ignore_index=True)
    frames["suppliers"] = pd.concat([frames["suppliers"], suppliers], ignore_index=True)
    frames["parts"] = pd.concat([frames["parts"], parts], ignore_index=True)
    frames["equipment"] = pd.concat([frames["equipment"], equipment], ignore_index=True)
    frames["equipment_links"] = pd.concat([frames["equipment_links"], equipment_links], ignore_index=True)
    frames["material_lots"] = pd.concat([frames["material_lots"], material_lots], ignore_index=True)
    frames["unit_lots"] = pd.concat([frames["unit_lots"], unit_lots], ignore_index=True)
    frames["lot_genealogy"] = pd.concat([frames["lot_genealogy"], pd.DataFrame(genealogy_rows)], ignore_index=True)
    frames["lots"] = pd.concat([frames["lots"], pd.DataFrame(lots_rows)], ignore_index=True)
    frames["inspection_results"] = pd.concat([frames["inspection_results"], pd.DataFrame(insp_rows)], ignore_index=True)
    frames["field_claims"] = pd.concat([frames["field_claims"], pd.DataFrame(claims)], ignore_index=True)
    frames["shipments"] = pd.concat([frames["shipments"], pd.DataFrame(shipments)], ignore_index=True)
    frames["supplier_alternatives"] = pd.concat([frames["supplier_alternatives"], alt], ignore_index=True)
    frames["production_runs"] = pd.concat([frames["production_runs"], runs], ignore_index=True)

    frames["_scenario_meta"] = pd.DataFrame([{"mold_lots": len(mold_lot_ids), "expected_q1": str(exp["Q1"]["unit_lots"])}])
    return frames
