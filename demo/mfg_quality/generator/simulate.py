"""背景データの乱数生成（事件行は inject が担当）。

背景は「事件と無関係な通常操業」:
- 2025-01〜2026-09 の平日に、3 製品それぞれの材料 → 成形 → サブ組立 → ユニット → 出荷の系譜を作る
- 成形は M-01..M-12（D-07 不調期間 5/12〜5/26 の M-07 は使わない）
- 背景品番は PA66-GF30 を使わない（Q7 の 7 点を汚さない）
- SX-5 の背景クレームは作らない（Q1 の 14 件を汚さない）
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

import pandas as pd

from demo.mfg_quality.generator.inject import (
    ASSEMBLY_LINE,
    PART_WEIGHT_KG,
    PRODUCT_MODELS,
    LotBook,
    assign_vins,
    mold_inspection_rows,
    subassy_lot_id,
    unit_lot_id,
)

BG_START = date(2025, 1, 6)
BG_END = date(2026, 9, 30)
AS_OF = date(2026, 10, 15)
D07_WINDOW = (date(2026, 5, 12), date(2026, 5, 26))
MACHINES = [f"M-{n:02d}" for n in range(1, 13)]
OTHER_PA66_PARTS = ["WH-210", "PG-320", "GR-150", "CL-80", "HS-40"]
BG_MATERIALS = ["POM-M90", "PBT-GF15", "PP-T20"]


def _scaled(n: int, scale: float, floor: int = 0) -> int:
    return max(floor, int(round(n * scale)))


def _weekdays(start: date, end: date) -> list[date]:
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _append(frames: dict[str, pd.DataFrame], name: str, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return
    base = frames.get(name)
    frames[name] = df if base is None or base.empty else pd.concat([base, df], ignore_index=True)


def _round10(x: float) -> int:
    return max(10, int(round(x / 10.0)) * 10)


class _BgBook(LotBook):
    """既存 ID と衝突しないよう連番を進める LotBook。"""

    def __init__(self, used: set[str]) -> None:
        super().__init__(edge_prefix="EB")
        self.used = used
        self._mold_seq: dict[tuple[str, str], int] = {}

    def produce(self, lot_id: str, *args: Any, **kw: Any) -> str:  # type: ignore[override]
        if lot_id in self.used:
            raise RuntimeError(f"duplicate lot id {lot_id}")
        self.used.add(lot_id)
        return super().produce(lot_id, *args, **kw)

    def bg_mold(self, material: str, part_no: str, prod: date, machine: str, qty: int, rng: random.Random) -> str:
        key = (material, part_no)
        while True:
            self._mold_seq[key] = self._mold_seq.get(key, 0) + 1
            candidate = f"ML-{material.removeprefix('HC-')}-{part_no.replace('-', '')}-{self._mold_seq[key]:02d}"
            if candidate not in self.used:
                break
        kg = round(qty * PART_WEIGHT_KG[part_no], 1)
        shift = rng.choice(["A", "B"])
        return self.produce(candidate, "MOLD", part_no, prod, machine, qty, [(material, kg)], shift=shift, operator=f"OP-{rng.randint(10, 29)}")

    def bg_assemble(self, part_no: str, prod: date, inputs: list[tuple[str, float]], rng: random.Random, *, unit: bool = False) -> str:
        qty = int(sum(q for _, q in inputs))
        if unit:
            lot_id = unit_lot_id(part_no, prod)
            lot_type = "UNIT"
        else:
            seq = 1
            lot_id = subassy_lot_id(part_no, prod, seq)
            while lot_id in self.used:
                seq += 1
                lot_id = subassy_lot_id(part_no, prod, seq)
            lot_type = "SUBASSY"
        return self.produce(lot_id, lot_type, part_no, prod, ASSEMBLY_LINE[part_no], qty, inputs, operator=f"OP-{rng.randint(30, 59)}")


def _bg_masters(frames: dict[str, pd.DataFrame], targets: dict[str, Any], scale: float, rng: random.Random) -> list[str]:
    """背景サプライヤ・品番・BOM・代替サプライヤ。背景の成形品番リストを返す。"""
    n_sup_total = _scaled(int(targets.get("suppliers", 40)), scale, floor=10)
    n_bg_sup = max(6, n_sup_total - len(frames["suppliers"]))
    plants = ["浜松工場", "岡崎工場", "太田工場", "いわき工場", "熊本工場", "四日市工場"]
    sup_rows = [
        {
            "supplier_id": f"SUP-BG-{i:03d}",
            "name": f"協力会社 {i:03d}",
            "tier": 3 if i <= 3 else rng.choice([1, 2, 2, 3]),
            "country": "JP" if rng.random() < 0.85 else rng.choice(["TH", "CN", "VN"]),
            "plant": rng.choice(plants),
        }
        for i in range(1, n_bg_sup + 1)
    ]
    _append(frames, "suppliers", sup_rows)
    bg_sup = [r["supplier_id"] for r in sup_rows]
    material_sup = {m: bg_sup[i] for i, m in enumerate(BG_MATERIALS)}

    n_parts_total = _scaled(int(targets.get("parts", 350)), scale, floor=30)
    n_bg_parts = max(10, n_parts_total - len(frames["parts"]) - len(BG_MATERIALS))
    part_rows = [
        {"part_no": m, "name": f"{m} 樹脂ペレット", "category": "材料", "material_spec": m, "supplier_id": material_sup[m]}
        for m in BG_MATERIALS
    ]
    molded: list[str] = []
    others: list[str] = []
    names = {"成形品": ["ブラケット", "カバー", "ブッシュ", "ギア", "クリップ", "ホルダ"], "購入品": ["ベアリング", "シャフト", "ボルト", "ハーネス", "モータ"], "サブ組立": ["ギア組立", "ブラケット組立", "カバー組立"]}
    for i in range(1, n_bg_parts + 1):
        cat = rng.choices(["成形品", "購入品", "サブ組立"], weights=[5, 3, 2])[0]
        no = f"P-BG-{i:04d}"
        part_rows.append(
            {
                "part_no": no,
                "name": f"{rng.choice(names[cat])} {no[-4:]}",
                "category": cat,
                "material_spec": rng.choice(BG_MATERIALS) if cat == "成形品" else "-",
                "supplier_id": rng.choice(bg_sup[3:] or bg_sup),
            }
        )
        (molded if cat == "成形品" else others).append(no)
    _append(frames, "parts", part_rows)
    spec = {r["part_no"]: r["material_spec"] for r in part_rows}

    n_bom_total = _scaled(int(targets.get("bom", 900)), scale, floor=20)
    existing_pairs = set(zip(frames["bom"]["parent_part_no"], frames["bom"]["child_part_no"], strict=True))
    bom_rows: list[dict[str, Any]] = []

    def add_bom(parent: str, child: str, qty: float) -> None:
        if parent == child or (parent, child) in existing_pairs:
            return
        existing_pairs.add((parent, child))
        bom_rows.append({"parent_part_no": parent, "child_part_no": child, "qty_per": qty, "valid_from": date(2024, 4, 1), "valid_to": date(2027, 3, 31)})

    for p in molded:
        add_bom(p, spec[p], round(rng.uniform(0.01, 0.2), 3))
    subs = [r["part_no"] for r in part_rows if r["category"] == "サブ組立"]
    children = molded + [r["part_no"] for r in part_rows if r["category"] == "購入品"]
    budget = n_bom_total - len(frames["bom"]) - len(bom_rows)
    guard, max_tries = 0, max(0, budget) * 20
    while budget > 0 and subs and children and guard < max_tries:
        guard += 1
        before = len(bom_rows)
        add_bom(rng.choice(subs), rng.choice(children), rng.choice([1, 1, 2, 4]))
        budget -= len(bom_rows) - before
    _append(frames, "bom", bom_rows)

    n_alt_total = _scaled(int(targets.get("supplier_alternatives", 30)), scale, floor=10)
    alt_rows = []
    for p in molded[: max(3, n_alt_total - len(frames["supplier_alternatives"]))]:
        mat = spec[p]
        alt = rng.choice([s for s in bg_sup if s != material_sup[mat]])
        alt_rows.append({"material_part_no": mat, "part_no": p, "supplier_id": material_sup[mat], "alt_supplier_id": alt, "ppap_status": rng.choice(["APPROVED", "APPROVED", "PENDING", "REJECTED"])})
    _append(frames, "supplier_alternatives", alt_rows)
    return molded


def _material_schedule(book: _BgBook, n: int, rng: random.Random) -> list[tuple[date, str]]:
    """背景の PA66-GF30 材料ロット（受入日順）。"""
    start = date(2024, 11, 18)
    span = (BG_END - start).days
    per_month: dict[str, int] = {}
    out: list[tuple[date, str]] = []
    for i in range(n):
        d = start + timedelta(days=int(span * i / max(1, n)) + rng.randint(0, 2))
        ym = f"{d:%y%m}"
        k = per_month.get(ym, 100) + 1
        while ym == "2605" and k in (117, 121):
            k += 1
        per_month[ym] = k
        lot_id = f"HC-{ym}-{k:03d}"
        book.used.add(lot_id)
        book.material_lot(lot_id, d, float(rng.choice([800, 1000, 1200, 1500])), round(rng.uniform(0.04, 0.1), 3))
        out.append((d, lot_id))
    return out


def _pick_material(schedule: list[tuple[date, str]], when: date) -> str:
    chosen = schedule[0][1]
    for d, lot in schedule:
        if d < when:
            chosen = lot
        else:
            break
    return chosen


def _pick_machine(when: date, rng: random.Random) -> str:
    pool = MACHINES
    if D07_WINDOW[0] <= when <= D07_WINDOW[1]:
        pool = [m for m in MACHINES if m != "M-07"]
    return rng.choice(pool)


def fill_background(
    frames: dict[str, pd.DataFrame],
    scenario: dict[str, Any],
    *,
    scale: float,
    rng: random.Random,
) -> dict[str, pd.DataFrame]:
    targets = scenario.get("table_targets", {})
    out = dict(frames)

    _bg_masters(out, targets, scale, rng)

    used = set(out["lots"]["lot_id"].astype(str))
    book = _BgBook(used)
    n_mat = _scaled(int(targets.get("material_lots", 300)), scale, floor=6) - len(out["material_lots"])
    schedule = _material_schedule(book, max(4, n_mat), rng)

    # --- ユニットの系譜（製品ごとに平日から日付を抽選）---
    weekdays = _weekdays(BG_START, BG_END)
    incident_units = set(out["unit_lots"]["lot_id"].astype(str))
    n_units = _scaled(int(targets.get("unit_lots", 1200)), scale, floor=9) - len(incident_units)
    per_product = max(3, n_units // 3)
    units: list[tuple[str, date, int]] = []
    for product in ("EPS-A200", "EPS-A210", "PWR-55"):
        days = [d for d in weekdays if unit_lot_id(product, d) not in incident_units]
        picked = sorted(rng.sample(days, min(per_product, len(days))))
        for u_date in picked:
            qty = _round10(rng.uniform(800, 2000))
            if product == "EPS-A200":
                m_date = u_date - timedelta(days=rng.randint(8, 16))
                ml = book.bg_mold(_pick_material(schedule, m_date), "WH-200", m_date, _pick_machine(m_date, rng), qty, rng)
                sa = book.bg_assemble("SUB-A200", u_date - timedelta(days=rng.randint(2, 4)), [(ml, qty)], rng)
                u = book.bg_assemble("EPS-A200", u_date, [(sa, qty)], rng, unit=True)
            elif product == "EPS-A210":
                m_date = u_date - timedelta(days=rng.randint(18, 26))
                ml = book.bg_mold(_pick_material(schedule, m_date), "WH-200", m_date, _pick_machine(m_date, rng), qty, rng)
                s1 = book.bg_assemble("SUB-A210-1", u_date - timedelta(days=rng.randint(13, 16)), [(ml, qty)], rng)
                s2 = book.bg_assemble("SUB-A210-2", u_date - timedelta(days=rng.randint(7, 10)), [(s1, qty)], rng)
                s3 = book.bg_assemble("SUB-A210-3", u_date - timedelta(days=rng.randint(2, 4)), [(s2, qty)], rng)
                u = book.bg_assemble("EPS-A210", u_date, [(s3, qty)], rng, unit=True)
            else:
                m_date = u_date - timedelta(days=rng.randint(14, 20))
                ml = book.bg_mold(_pick_material(schedule, m_date), "PG-310", m_date, _pick_machine(m_date, rng), qty, rng)
                s1 = book.bg_assemble("SUB-P55-1", u_date - timedelta(days=rng.randint(8, 11)), [(ml, qty)], rng)
                s2 = book.bg_assemble("SUB-P55-2", u_date - timedelta(days=rng.randint(2, 5)), [(s1, qty)], rng)
                u = book.bg_assemble("PWR-55", u_date, [(s2, qty)], rng, unit=True)
            units.append((u, u_date, qty))

    # --- 他の PA66-GF30 成形品（系譜はここで止まる＝他拠点向け出荷）---
    n_other = _scaled(int(targets.get("other_mold_lots", 300)), scale, floor=5)
    other_molds: list[tuple[str, str, date, int]] = []
    for _ in range(n_other):
        m_date = rng.choice(weekdays)
        part_no = rng.choice(OTHER_PA66_PARTS)
        qty = _round10(rng.uniform(1000, 4000))
        ml = book.bg_mold(_pick_material(schedule, m_date), part_no, m_date, _pick_machine(m_date, rng), qty, rng)
        other_molds.append((ml, part_no, m_date, qty))

    _append(out, "material_lots", book.material)
    _append(out, "lots", book.lots)
    _append(out, "lot_genealogy", book.genealogy)
    _append(out, "production_runs", book.runs)
    _append(out, "unit_lots", book.units)

    # --- 検査（背景の成形ロット: バックラッシは USL の 50〜70%）---
    bg_molds = [r["lot_id"] for r in book.lots if r["lot_type"] == "MOLD"]
    insp_rows: list[dict[str, Any]] = []
    for lot_id in bg_molds:
        insp_rows.extend(
            mold_inspection_rows(
                lot_id,
                backlash_ratios=[round(rng.uniform(0.5, 0.7), 3) for _ in range(3)],
                od_offsets=[round(rng.uniform(-0.03, 0.03), 4) for _ in range(2)],
                profile=[round(rng.uniform(0.004, 0.014), 4) for _ in range(2)],
            )
        )
    _append(out, "inspection_results", insp_rows)

    # --- 工程内不良（背景ロットのみ）---
    n_def = _scaled(int(targets.get("defects", 1500)), scale, floor=5)
    defect_kinds = [("寸法", "外径公差外れ"), ("欠け", "ゲート部欠け"), ("バリ", "パーティング部バリ"), ("ショート", "充填不足"), ("ヒケ", "リブ部ヒケ"), ("外観その他", "表面キズ")]
    pool = bg_molds + [r["lot_id"] for r in book.lots if r["lot_type"] == "SUBASSY"]
    def_rows = []
    for i in range(1, n_def + 1):
        code, note = rng.choice(defect_kinds)
        def_rows.append({"defect_id": f"DEF-BG-{i:05d}", "lot_id": rng.choice(pool), "defect_code": code, "qty": rng.randint(1, 30), "note": note})
    _append(out, "defects", def_rows)

    # --- 出荷（ユニットを 1〜3 回に分割。直近製造分は一部在庫）---
    oem_of = {model: oem for pairs in PRODUCT_MODELS.values() for oem, model in pairs}
    part_of_unit = {r["lot_id"]: r["part_no"] for r in book.units}
    ship_rows: list[dict[str, Any]] = []
    inv_rows: list[dict[str, Any]] = []
    for u, u_date, qty in units:
        product = part_of_unit[u]
        recent = u_date > date(2026, 9, 18)
        shipped_total = _round10(qty * rng.uniform(0.3, 0.7)) if recent else qty
        k = rng.randint(1, 3)
        remaining = shipped_total
        s_date = u_date + timedelta(days=rng.randint(3, 8))
        for j in range(k):
            q = remaining if j == k - 1 else _round10(shipped_total / k)
            q = min(q, remaining)
            if q <= 0:
                break
            remaining -= q
            model = rng.choice([m for _, m in PRODUCT_MODELS[product]])
            ship_rows.append({"unit_lot_id": u, "oem_id": oem_of[model], "model_code": model, "ship_date": min(s_date, AS_OF), "qty": q})
            s_date += timedelta(days=rng.randint(3, 9))
        if qty - shipped_total > 0:
            inv_rows.append({"lot_id": u, "part_no": product, "holder_supplier_id": "SUP-T1", "tier": 1, "location": "豊浜工場 完成品倉庫", "qty": qty - shipped_total, "as_of_date": AS_OF})
    for ml, part_no, m_date, qty in other_molds:
        if m_date >= date(2026, 8, 20):
            inv_rows.append({"lot_id": ml, "part_no": part_no, "holder_supplier_id": "SUP-T2", "tier": 2, "location": "三協モールド 成形品倉庫", "qty": _round10(qty * rng.uniform(0.2, 0.8)), "as_of_date": AS_OF})
    for i, row in enumerate(inv_rows, start=1):
        row["inventory_id"] = f"INV-B{i:05d}"
    _append(out, "inventory", inv_rows)

    ship_all = pd.concat([out["shipments"], pd.DataFrame(ship_rows)], ignore_index=True) if ship_rows else out["shipments"]
    ship_all = ship_all.sort_values(["ship_date", "unit_lot_id", "model_code"], kind="stable").reset_index(drop=True)
    years = pd.to_datetime(ship_all["ship_date"]).dt.strftime("%y")
    seq = ship_all.groupby(years).cumcount() + 1
    ship_all["shipment_id"] = [f"SHP-{y}{n:05d}" for y, n in zip(years, seq, strict=True)]

    # --- 背景クレーム（CV-3 / KX-1 / VN-7 のみ。SX-5 は事件の 14 件だけ）---
    n_claims = _scaled(int(targets.get("field_claims", 800)), scale, floor=17) - len(out["field_claims"])
    symptoms = [
        ("ELECTRICAL", "警告灯点灯"),
        ("WATER", "ドア下部から雨漏り"),
        ("NOISE", "ブレーキ鳴き"),
        ("NOISE", "高速走行時の風切り音"),
        ("VIBRATION", "アイドリング時の振動"),
        ("FUNCTION", "ウィンドウ昇降が遅い"),
        ("FUNCTION", "ステアリングが重い"),
    ]
    eligible = ship_all[(ship_all["model_code"] != "SX-5") & (ship_all["unit_lot_id"].isin(set(part_of_unit)))]
    eligible = eligible[pd.to_datetime(eligible["ship_date"]) < pd.Timestamp(2026, 9, 1)]
    claim_rows: list[dict[str, Any]] = []
    counters: dict[tuple[str, int], int] = {}
    if len(eligible):
        idx = eligible.index.tolist()
        for _ in range(max(0, n_claims)):
            row = ship_all.loc[rng.choice(idx)]
            c_date = min(row["ship_date"] + timedelta(days=rng.randint(30, 400)), date(2026, 10, 31))
            model = str(row["model_code"])
            key = (model, c_date.year)
            counters[key] = counters.get(key, 0) + 1
            code, text = rng.choice(symptoms)
            claim_rows.append(
                {
                    "claim_id": f"CLM-{model.replace('-', '')}-{c_date.year}-{counters[key]:03d}",
                    "oem_id": row["oem_id"],
                    "model_code": model,
                    "vin": None,
                    "unit_lot_id": row["unit_lot_id"],
                    "claim_date": c_date,
                    "symptom_code": code,
                    "symptom_text": text,
                }
            )
    claims_all = pd.concat([out["field_claims"], pd.DataFrame(claim_rows)], ignore_index=True) if claim_rows else out["field_claims"]
    out["shipments"], out["field_claims"] = assign_vins(ship_all, claims_all)
    return out
