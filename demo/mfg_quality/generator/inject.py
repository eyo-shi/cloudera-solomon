"""scenario.yaml の事件データを固定 ID で注入。

ロット系譜の向き: child_lot_id（投入側）→ parent_lot_id（生成側）。

事件の系譜（D-07 不調期間に M-07 で成形した 15 ロットの下流）:

  HC-2605-117（9 成形ロット）
    WH-200 ×3 → SA-A200 ×3 → U-A200-260601..03 → SX-5            （3 段）
    WH-200 ×3 → SA-A210-1 → SA-A210-2 → SA-A210-3 → U-A210 ×2 → CV-3 / KX-1（5 段）
    PG-310 ×3 → SA-P55-1 ×2 → SA-P55-2 → U-P55 ×2 → VN-7 / Tier1 在庫（4 段）
  HC-2605-121（6 成形ロット）
    WH-200 ×2 → SA-A200 → U-A200-260605 → SX-5
    WH-200 ×2 → SA-A200（Tier1 在庫）
    WH-200 ×2（Tier2 在庫）
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

PLANT_TOYOHAMA = "豊浜工場"
PLANT_KITAMI = "北見工場"

# 成形品 1 個あたりの樹脂使用量 kg（材料 → 成形の qty_used に使う）
PART_WEIGHT_KG = {
    "WH-200": 0.098,
    "WH-210": 0.12,
    "PG-310": 0.095,
    "PG-320": 0.09,
    "GR-150": 0.06,
    "CL-80": 0.01,
    "HS-40": 0.02,
}

# 品番 → 生産設備（成形以外）
ASSEMBLY_LINE = {
    "SUB-A200": "L-A200",
    "EPS-A200": "L-A200",
    "SUB-A210-1": "L-A210",
    "SUB-A210-2": "L-A210",
    "SUB-A210-3": "L-A210",
    "EPS-A210": "L-A210",
    "SUB-P55-1": "L-P55",
    "SUB-P55-2": "L-P55",
    "PWR-55": "L-P55",
}

# ユニット品番 → 出荷先車種
PRODUCT_MODELS = {
    "EPS-A200": [("OEM-MIRAI", "SX-5")],
    "EPS-A210": [("OEM-MIRAI", "CV-3"), ("OEM-MIRAI", "KX-1")],
    "PWR-55": [("OEM-YAMATO", "VN-7")],
}

BACKLASH_USL = 0.15
BACKLASH_LSL = 0.05


def _empty_frames(schemas: dict[str, list]) -> dict[str, pd.DataFrame]:
    return {name: pd.DataFrame(columns=[c["name"] for c in cols]) for name, cols in schemas.items()}


def mold_lot_id(material_lot: str, part_no: str, seq: int) -> str:
    """ML-<材料ロット yyMM-nnn>-<品番（ハイフンなし）>-<連番>。"""
    return f"ML-{material_lot.removeprefix('HC-')}-{part_no.replace('-', '')}-{seq:02d}"


def subassy_lot_id(part_no: str, prod: date, seq: int = 1) -> str:
    """SA-<サブ組立品番（SUB- なし）>-<yymmdd>-<連番>。"""
    return f"SA-{part_no.removeprefix('SUB-')}-{prod:%y%m%d}-{seq:02d}"


def unit_lot_id(part_no: str, prod: date) -> str:
    """U-<品番略>-<yymmdd>。"""
    abbr = {"EPS-A200": "A200", "EPS-A210": "A210", "PWR-55": "P55"}[part_no]
    return f"U-{abbr}-{prod:%y%m%d}"


def masters() -> dict[str, pd.DataFrame]:
    """固定マスタ（OEM・車種・サプライヤ・品番・設備・BOM）。"""
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
            {"supplier_id": "SUP-T1", "name": "東邦精機株式会社", "tier": 1, "country": "JP", "plant": PLANT_TOYOHAMA},
            {"supplier_id": "SUP-T2", "name": "三協モールド工業", "tier": 2, "country": "JP", "plant": PLANT_TOYOHAMA},
            {"supplier_id": "SUP-NC", "name": "北陸ケミカル", "tier": 3, "country": "JP", "plant": "富山工場"},
            {"supplier_id": "SUP-TP", "name": "東洋ポリマー", "tier": 3, "country": "JP", "plant": "四日市工場"},
        ]
    )

    def part(no: str, name: str, cat: str, spec: str, sup: str) -> dict[str, Any]:
        return {"part_no": no, "name": name, "category": cat, "material_spec": spec, "supplier_id": sup}

    parts = pd.DataFrame(
        [
            part("PA66-GF30", "PA66 ガラス繊維 30% 樹脂ペレット", "材料", "PA66-GF30", "SUP-NC"),
            part("WH-200", "ウォームホイール", "成形品", "PA66-GF30", "SUP-T2"),
            part("WH-210", "ウォームホイール（大径）", "成形品", "PA66-GF30", "SUP-T2"),
            part("PG-310", "パワーウィンドウ用ギア", "成形品", "PA66-GF30", "SUP-T2"),
            part("PG-320", "パワーウィンドウ用ギア（後席）", "成形品", "PA66-GF30", "SUP-T2"),
            part("GR-150", "リダクションギア", "成形品", "PA66-GF30", "SUP-T2"),
            part("CL-80", "ケーブルクリップ", "成形品", "PA66-GF30", "SUP-T2"),
            part("HS-40", "ハーネスホルダ", "成形品", "PA66-GF30", "SUP-T2"),
            part("SUB-A200", "EPS ギアボックス組立（A200）", "サブ組立", "-", "SUP-T1"),
            part("SUB-A210-1", "EPS ギアボックス組立（A210）", "サブ組立", "-", "SUP-T1"),
            part("SUB-A210-2", "EPS 減速機組立（A210）", "サブ組立", "-", "SUP-T1"),
            part("SUB-A210-3", "EPS モータ結合組立（A210）", "サブ組立", "-", "SUP-T1"),
            part("SUB-P55-1", "レギュレータギア組立", "サブ組立", "-", "SUP-T1"),
            part("SUB-P55-2", "レギュレータ駆動部組立", "サブ組立", "-", "SUP-T1"),
            part("EPS-A200", "EPS ユニット（SX-5 向け）", "ユニット", "-", "SUP-T1"),
            part("EPS-A210", "EPS ユニット（CV-3 / KX-1 向け）", "ユニット", "-", "SUP-T1"),
            part("PWR-55", "パワーウィンドウレギュレータ（VN-7 向け）", "ユニット", "-", "SUP-T1"),
        ]
    )

    def bom(parent: str, child: str, qty: float = 1) -> dict[str, Any]:
        return {
            "parent_part_no": parent,
            "child_part_no": child,
            "qty_per": qty,
            "valid_from": date(2024, 4, 1),
            "valid_to": date(2027, 3, 31),
        }

    bom_rows = [
        bom("WH-200", "PA66-GF30", PART_WEIGHT_KG["WH-200"]),
        bom("WH-210", "PA66-GF30", PART_WEIGHT_KG["WH-210"]),
        bom("PG-310", "PA66-GF30", PART_WEIGHT_KG["PG-310"]),
        bom("PG-320", "PA66-GF30", PART_WEIGHT_KG["PG-320"]),
        bom("GR-150", "PA66-GF30", PART_WEIGHT_KG["GR-150"]),
        bom("CL-80", "PA66-GF30", PART_WEIGHT_KG["CL-80"]),
        bom("HS-40", "PA66-GF30", PART_WEIGHT_KG["HS-40"]),
        bom("SUB-A200", "WH-200"),
        bom("EPS-A200", "SUB-A200"),
        bom("SUB-A210-1", "WH-200"),
        bom("SUB-A210-2", "SUB-A210-1"),
        bom("SUB-A210-3", "SUB-A210-2"),
        bom("EPS-A210", "SUB-A210-3"),
        bom("SUB-P55-1", "PG-310"),
        bom("SUB-P55-2", "SUB-P55-1"),
        bom("PWR-55", "SUB-P55-2"),
    ]

    eq_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []
    for n in range(1, 13):
        m = f"M-{n:02d}"
        d = f"D-{n:02d}"
        eq_rows.append({"equipment_id": m, "name": f"成形機 {n} 号", "type": "成形機", "plant": PLANT_TOYOHAMA, "parent_equipment_id": None})
        eq_rows.append({"equipment_id": d, "name": f"ホッパードライヤー {n}", "type": "乾燥機", "plant": PLANT_TOYOHAMA, "parent_equipment_id": m})
        link_rows.append({"edge_id": f"EL-{d.replace('-', '')}-{m.replace('-', '')}", "equipment_id": d, "parent_equipment_id": m})
    eq_rows += [
        {"equipment_id": "K-03", "name": "北見 成形機 3 号", "type": "成形機", "plant": PLANT_KITAMI, "parent_equipment_id": None},
        {"equipment_id": "L-A200", "name": "EPS-A200 組立ライン", "type": "組立ライン", "plant": PLANT_TOYOHAMA, "parent_equipment_id": None},
        {"equipment_id": "L-A210", "name": "EPS-A210 組立ライン", "type": "組立ライン", "plant": PLANT_TOYOHAMA, "parent_equipment_id": None},
        {"equipment_id": "L-P55", "name": "PWR-55 組立ライン", "type": "組立ライン", "plant": PLANT_TOYOHAMA, "parent_equipment_id": None},
    ]

    return {
        "oem_customers": oems,
        "vehicle_models": models,
        "suppliers": suppliers,
        "parts": parts,
        "bom": pd.DataFrame(bom_rows),
        "equipment": pd.DataFrame(eq_rows),
        "equipment_links": pd.DataFrame(link_rows),
    }


class LotBook:
    """lots / lot_genealogy / production_runs / unit_lots を一貫して積む。"""

    def __init__(self, edge_prefix: str = "EG") -> None:
        self.lots: list[dict[str, Any]] = []
        self.genealogy: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []
        self.units: list[dict[str, Any]] = []
        self.material: list[dict[str, Any]] = []
        self._edge_prefix = edge_prefix
        self._edge_seq = 0

    def material_lot(self, lot_id: str, receipt: date, qty_kg: float, moisture: float, *, plant: str = PLANT_TOYOHAMA) -> str:
        self.material.append(
            {
                "lot_id": lot_id,
                "part_no": "PA66-GF30",
                "supplier_id": "SUP-NC",
                "receipt_date": receipt,
                "qty_kg": qty_kg,
                "coa_moisture_pct": moisture,
            }
        )
        self.lots.append(
            {"lot_id": lot_id, "lot_type": "MATERIAL", "part_no": "PA66-GF30", "plant": plant, "prod_date": receipt, "equipment_id": None, "qty": int(qty_kg)}
        )
        return lot_id

    def produce(
        self,
        lot_id: str,
        lot_type: str,
        part_no: str,
        prod: date,
        equipment_id: str,
        qty: int,
        inputs: list[tuple[str, float]],
        *,
        plant: str = PLANT_TOYOHAMA,
        shift: str = "A",
        operator: str = "OP-12",
    ) -> str:
        self.lots.append(
            {"lot_id": lot_id, "lot_type": lot_type, "part_no": part_no, "plant": plant, "prod_date": prod, "equipment_id": equipment_id, "qty": qty}
        )
        for child, qty_used in inputs:
            self._edge_seq += 1
            self.genealogy.append(
                {"edge_id": f"{self._edge_prefix}-{self._edge_seq:06d}", "child_lot_id": child, "parent_lot_id": lot_id, "qty_used": qty_used}
            )
        start_hour = 8 if shift == "A" else 16
        start = datetime(prod.year, prod.month, prod.day, start_hour, 0)
        self.runs.append(
            {
                "run_id": f"RUN-{lot_id}",
                "equipment_id": equipment_id,
                "output_lot_id": lot_id,
                "part_no": part_no,
                "start_ts": start,
                "end_ts": start + timedelta(hours=8),
                "qty": qty,
                "operator_id": operator,
                "shift": shift,
            }
        )
        if lot_type == "UNIT":
            self.units.append({"lot_id": lot_id, "part_no": part_no, "plant": plant, "prod_date": prod, "qty": qty})
        return lot_id

    def mold(self, material: str, part_no: str, seq: int, prod: date, machine: str, qty: int, **kw: Any) -> str:
        lot_id = mold_lot_id(material, part_no, seq)
        kg = round(qty * PART_WEIGHT_KG[part_no], 1)
        return self.produce(lot_id, "MOLD", part_no, prod, machine, qty, [(material, kg)], **kw)

    def assemble(self, part_no: str, prod: date, inputs: list[tuple[str, float]], *, seq: int = 1, lot_type: str = "SUBASSY", **kw: Any) -> str:
        qty = int(sum(q for _, q in inputs))
        if lot_type == "UNIT":
            lot_id = unit_lot_id(part_no, prod)
        else:
            lot_id = subassy_lot_id(part_no, prod, seq)
        return self.produce(lot_id, lot_type, part_no, prod, ASSEMBLY_LINE[part_no], qty, inputs, **kw)


def assign_vins(shipments: pd.DataFrame, claims: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """出荷日順に車種ごとの連番 VIN 範囲を振り、クレームの VIN を範囲内に合わせる。"""
    if shipments.empty:
        return shipments, claims
    ship = shipments.sort_values(["ship_date", "shipment_id"]).reset_index(drop=True)
    counters: dict[str, int] = {}
    vin_from: list[str] = []
    vin_to: list[str] = []
    for model, qty in zip(ship["model_code"], ship["qty"], strict=True):
        start = counters.get(model, 100001)
        end = start + int(qty) - 1
        counters[model] = end + 1
        prefix = str(model).replace("-", "")
        vin_from.append(f"{prefix}-{start:07d}")
        vin_to.append(f"{prefix}-{end:07d}")
    ship["vin_from"] = vin_from
    ship["vin_to"] = vin_to

    if claims.empty:
        return ship, claims
    claims = claims.copy()
    ranges: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for _, row in ship.iterrows():
        a = int(str(row["vin_from"]).rsplit("-", 1)[1])
        b = int(str(row["vin_to"]).rsplit("-", 1)[1])
        ranges.setdefault((str(row["unit_lot_id"]), str(row["model_code"])), []).append((a, b))
    used: dict[tuple[str, str], int] = {}
    vins: list[str] = []
    for _, row in claims.iterrows():
        key = (str(row["unit_lot_id"]), str(row["model_code"]))
        spans = ranges.get(key)
        if not spans:
            vins.append(str(row.get("vin") or ""))
            continue
        k = used.get(key, 0)
        used[key] = k + 1
        a, b = spans[k % len(spans)]
        # 同じ範囲内で重ならないように散らす
        offset = (k * 37 + 11) % max(1, b - a + 1)
        vins.append(f"{str(row['model_code']).replace('-', '')}-{a + offset:07d}")
    claims["vin"] = vins
    return ship, claims


def inject_scenario(scenario: dict[str, Any], schemas: dict[str, list]) -> dict[str, pd.DataFrame]:
    """事件・隠し事実の行を構築（背景は simulate が埋める）。"""
    frames = _empty_frames(schemas)
    inc = scenario["incident"]
    m = masters()

    book = LotBook(edge_prefix="EG")
    mat117 = book.material_lot("HC-2605-117", date(2026, 5, 10), 1200, 0.08)
    mat121 = book.material_lot("HC-2605-121", date(2026, 5, 18), 800, 0.07)

    # --- 成形（すべて M-07、D-07 不調期間 5/12–5/26 内）---
    d = date
    wh117 = [
        book.mold(mat117, "WH-200", 1, d(2026, 5, 14), "M-07", 1500),
        book.mold(mat117, "WH-200", 2, d(2026, 5, 14), "M-07", 1400, shift="B", operator="OP-15"),
        book.mold(mat117, "WH-200", 3, d(2026, 5, 14), "M-07", 1200, shift="B", operator="OP-15"),
        book.mold(mat117, "WH-200", 4, d(2026, 5, 15), "M-07", 1800),
        book.mold(mat117, "WH-200", 5, d(2026, 5, 15), "M-07", 1800, shift="B", operator="OP-15"),
        book.mold(mat117, "WH-200", 6, d(2026, 5, 15), "M-07", 1800, shift="B", operator="OP-15"),
    ]
    pg117 = [
        book.mold(mat117, "PG-310", 1, d(2026, 5, 16), "M-07", 900, operator="OP-21"),
        book.mold(mat117, "PG-310", 2, d(2026, 5, 16), "M-07", 900, operator="OP-21"),
        book.mold(mat117, "PG-310", 3, d(2026, 5, 16), "M-07", 740, shift="B", operator="OP-15"),
    ]
    wh121 = [
        book.mold(mat121, "WH-200", 1, d(2026, 5, 22), "M-07", 400),
        book.mold(mat121, "WH-200", 2, d(2026, 5, 22), "M-07", 300),
        book.mold(mat121, "WH-200", 3, d(2026, 5, 22), "M-07", 300, shift="B", operator="OP-15"),
        book.mold(mat121, "WH-200", 4, d(2026, 5, 24), "M-07", 300),
        book.mold(mat121, "WH-200", 5, d(2026, 5, 24), "M-07", 1600),
        book.mold(mat121, "WH-200", 6, d(2026, 5, 24), "M-07", 1500, shift="B", operator="OP-15"),
    ]

    # --- EPS-A200（3 段）---
    sa_a200 = [
        book.assemble("SUB-A200", d(2026, 5, 28), [(wh117[0], 1500)], operator="OP-31"),
        book.assemble("SUB-A200", d(2026, 5, 29), [(wh117[1], 1400)], operator="OP-31"),
        book.assemble("SUB-A200", d(2026, 5, 30), [(wh117[2], 1200)], operator="OP-31"),
        book.assemble("SUB-A200", d(2026, 6, 3), [(wh121[0], 400), (wh121[1], 300)], operator="OP-31"),
        book.assemble("SUB-A200", d(2026, 6, 4), [(wh121[2], 300), (wh121[3], 300)], operator="OP-31"),
    ]
    claim_units = []
    for row, sa in zip(inc["claim"]["unit_lots"], sa_a200[:3], strict=True):
        prod = date.fromisoformat(row["prod_date"])
        qty = next(r["qty"] for r in book.lots if r["lot_id"] == sa)
        u = book.assemble("EPS-A200", prod, [(sa, qty)], lot_type="UNIT", operator="OP-33")
        if u != row["lot_id"]:
            raise RuntimeError(f"unit lot id mismatch: {u} != {row['lot_id']}")
        claim_units.append(u)
    u_a200_121 = book.assemble("EPS-A200", d(2026, 6, 5), [(sa_a200[3], 700)], lot_type="UNIT", operator="OP-33")

    # --- EPS-A210（5 段）---
    sa1 = book.assemble("SUB-A210-1", d(2026, 5, 20), [(lot, 1800) for lot in wh117[3:6]], operator="OP-41")
    sa2 = book.assemble("SUB-A210-2", d(2026, 5, 25), [(sa1, 5400)], operator="OP-41")
    sa3 = book.assemble("SUB-A210-3", d(2026, 6, 1), [(sa2, 5400)], operator="OP-41")
    u_a210_a = book.assemble("EPS-A210", d(2026, 6, 8), [(sa3, 3200)], lot_type="UNIT", operator="OP-43")
    u_a210_b = book.assemble("EPS-A210", d(2026, 6, 9), [(sa3, 2200)], lot_type="UNIT", operator="OP-43")

    # --- PWR-55（4 段）---
    sp1a = book.assemble("SUB-P55-1", d(2026, 5, 19), [(pg117[0], 900), (pg117[1], 900)], operator="OP-51")
    sp1b = book.assemble("SUB-P55-1", d(2026, 5, 20), [(pg117[2], 740)], operator="OP-51")
    sp2 = book.assemble("SUB-P55-2", d(2026, 5, 26), [(sp1a, 1800), (sp1b, 740)], operator="OP-51")
    u_p55_a = book.assemble("PWR-55", d(2026, 6, 10), [(sp2, 1900)], lot_type="UNIT", operator="OP-53")
    u_p55_b = book.assemble("PWR-55", d(2026, 6, 11), [(sp2, 640)], lot_type="UNIT", operator="OP-53")

    # --- 過去事例（2024 北見、QR-2024-0815）---
    mat_kitami = book.material_lot("HC-2408-033", date(2024, 8, 1), 600, 0.09, plant=PLANT_KITAMI)
    ml_kitami = book.mold(mat_kitami, "PG-310", 1, d(2024, 8, 5), "K-03", 1200, plant=PLANT_KITAMI, operator="OP-K07")

    # --- 出荷（ユニットロット → 車種、数量は scenario containment と一致）---
    ship_plan = [
        (claim_units[0], "SX-5", d(2026, 6, 5), 800),
        (claim_units[0], "SX-5", d(2026, 6, 8), 700),
        (claim_units[1], "SX-5", d(2026, 6, 9), 700),
        (claim_units[1], "SX-5", d(2026, 6, 12), 700),
        (claim_units[2], "SX-5", d(2026, 6, 15), 600),
        (claim_units[2], "SX-5", d(2026, 6, 18), 600),
        (u_a200_121, "SX-5", d(2026, 6, 22), 700),
        (u_a210_a, "CV-3", d(2026, 6, 15), 1100),
        (u_a210_a, "KX-1", d(2026, 6, 20), 1100),
        (u_a210_a, "CV-3", d(2026, 6, 25), 1000),
        (u_a210_b, "KX-1", d(2026, 6, 26), 1200),
        (u_a210_b, "KX-1", d(2026, 7, 3), 1000),
        (u_p55_a, "VN-7", d(2026, 6, 18), 1000),
        (u_p55_a, "VN-7", d(2026, 7, 1), 900),
    ]
    model_oem = dict(zip(m["vehicle_models"]["model_code"], m["vehicle_models"]["oem_id"], strict=True))
    shipments = pd.DataFrame(
        [
            {
                "shipment_id": f"SHP-26{i:05d}",
                "unit_lot_id": unit,
                "oem_id": model_oem[model],
                "model_code": model,
                "ship_date": sdate,
                "qty": qty,
                "vin_from": None,
                "vin_to": None,
            }
            for i, (unit, model, sdate, qty) in enumerate(ship_plan, start=1)
        ]
    )

    # --- 在庫（Tier1 = 東邦精機、Tier2 = 三協モールド）---
    as_of = d(2026, 10, 15)
    inventory = pd.DataFrame(
        [
            {"inventory_id": "INV-260001", "lot_id": sa_a200[4], "part_no": "SUB-A200", "holder_supplier_id": "SUP-T1", "tier": 1, "location": "豊浜工場 組立仕掛", "qty": 600, "as_of_date": as_of},
            {"inventory_id": "INV-260002", "lot_id": u_p55_b, "part_no": "PWR-55", "holder_supplier_id": "SUP-T1", "tier": 1, "location": "豊浜工場 完成品倉庫", "qty": 640, "as_of_date": as_of},
            {"inventory_id": "INV-260003", "lot_id": wh121[4], "part_no": "WH-200", "holder_supplier_id": "SUP-T2", "tier": 2, "location": "三協モールド 成形品倉庫", "qty": 1600, "as_of_date": as_of},
            {"inventory_id": "INV-260004", "lot_id": wh121[5], "part_no": "WH-200", "holder_supplier_id": "SUP-T2", "tier": 2, "location": "三協モールド 成形品倉庫", "qty": 1500, "as_of_date": as_of},
        ]
    )

    # --- 検査（成形ロット: バックラッシは USL の 91〜93%、判定はすべて OK）---
    insp_rows: list[dict[str, Any]] = []
    incident_molds = wh117 + pg117 + wh121
    for lot_id in incident_molds:
        insp_rows.extend(mold_inspection_rows(lot_id, backlash_ratios=[0.91, 0.92, 0.93], od_offsets=[0.004, -0.006], profile=[0.008, 0.011]))
    insp_rows.extend(mold_inspection_rows(ml_kitami, backlash_ratios=[0.88, 0.89, 0.9], od_offsets=[0.002, -0.004], profile=[0.009, 0.01]))

    # --- 工程内不良（2024 北見の事例は 外観その他 で記録されていた）---
    defects = pd.DataFrame(
        [
            {
                "defect_id": "DEF-2024-0815-01",
                "lot_id": ml_kitami,
                "defect_code": "外観その他",
                "qty": 12,
                "note": "客先返却品。噛み合い部の打音（8D QR-2024-0815）",
            }
        ]
    )

    # --- クレーム（SX-5 14 件、Q1 の 3 ユニットロット）---
    symptoms = [
        "ハンドル操作時ゴトゴト",
        "ステアリングから打音",
        "低速コーナリングでカタカタ",
        "RATTLE noise on turn",
        "NOISE steering",
    ]
    claims = pd.DataFrame(
        [
            {
                "claim_id": f"CLM-SX5-2026-{i + 1:03d}",
                "oem_id": "OEM-MIRAI",
                "model_code": "SX-5",
                "vin": None,
                "unit_lot_id": claim_units[i % 3],
                "claim_date": date(2026, 10, 5 + i % 10),
                "symptom_code": "NOISE" if i % 2 == 0 else "RATTLE",
                "symptom_text": symptoms[i % len(symptoms)],
            }
            for i in range(int(inc["claim"]["count"]))
        ]
    )
    shipments, claims = assign_vins(shipments, claims)

    # --- 代替サプライヤ（PA66-GF30 を使う 7 部品、北陸ケミカル → 東洋ポリマー）---
    q7 = scenario.get("q7_ppap") or {}
    alt_rows = []
    for status, key in (("APPROVED", "approved_parts"), ("PENDING", "pending_parts")):
        for part_no in q7.get(key) or []:
            alt_rows.append(
                {"material_part_no": "PA66-GF30", "part_no": part_no, "supplier_id": "SUP-NC", "alt_supplier_id": "SUP-TP", "ppap_status": status}
            )

    fixed = {
        **m,
        "material_lots": pd.DataFrame(book.material),
        "lots": pd.DataFrame(book.lots),
        "lot_genealogy": pd.DataFrame(book.genealogy),
        "production_runs": pd.DataFrame(book.runs),
        "unit_lots": pd.DataFrame(book.units),
        "inspection_results": pd.DataFrame(insp_rows),
        "defects": defects,
        "field_claims": claims,
        "shipments": shipments,
        "inventory": inventory,
        "supplier_alternatives": pd.DataFrame(alt_rows),
    }
    for name, df in fixed.items():
        if name in frames:
            frames[name] = pd.concat([frames[name], df], ignore_index=True) if len(frames[name]) else df
        else:
            frames[name] = df

    frames["_incident"] = pd.DataFrame(
        [{"lot_id": lot_id, "kind": "incident_mold"} for lot_id in incident_molds]
        + [{"lot_id": lot_id, "kind": "incident_lot"} for lot_id in [r["lot_id"] for r in book.lots]]
    )
    return frames


def mold_inspection_rows(
    lot_id: str,
    *,
    backlash_ratios: list[float],
    od_offsets: list[float],
    profile: list[float],
) -> list[dict[str, Any]]:
    """成形ロットの検査行（バックラッシ / 外径 / 歯形）。"""
    rows: list[dict[str, Any]] = []
    for i, r in enumerate(backlash_ratios, start=1):
        rows.append(
            {"insp_id": f"INSP-{lot_id}-BL{i}", "lot_id": lot_id, "item": "バックラッシ", "value": round(BACKLASH_USL * r, 5), "lsl": BACKLASH_LSL, "usl": BACKLASH_USL, "judgment": "OK"}
        )
    for i, off in enumerate(od_offsets, start=1):
        rows.append(
            {"insp_id": f"INSP-{lot_id}-OD{i}", "lot_id": lot_id, "item": "外径", "value": round(60.0 + off, 4), "lsl": 59.95, "usl": 60.05, "judgment": "OK"}
        )
    for i, v in enumerate(profile, start=1):
        rows.append(
            {"insp_id": f"INSP-{lot_id}-PR{i}", "lot_id": lot_id, "item": "歯形", "value": round(v, 4), "lsl": 0.0, "usl": 0.02, "judgment": "OK"}
        )
    return rows
