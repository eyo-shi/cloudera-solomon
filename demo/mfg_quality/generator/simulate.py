"""背景データの乱数生成（事件行は inject が担当）。"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

import pandas as pd


def _scaled(n: int, scale: float, floor: int = 0) -> int:
    return max(floor, int(n * scale))


def fill_background(
    frames: dict[str, pd.DataFrame],
    scenario: dict[str, Any],
    *,
    scale: float,
    rng: random.Random,
) -> dict[str, pd.DataFrame]:
    targets = scenario.get("table_targets", {})
    out = dict(frames)

    n_sup = _scaled(targets.get("suppliers", 40), scale, floor=4)
    if len(out["suppliers"]) < n_sup:
        rows = []
        for i in range(len(out["suppliers"]), n_sup):
            rows.append(
                {
                    "supplier_id": f"SUP-BG-{i:03d}",
                    "name": f"背景サプライヤ {i}",
                    "tier": rng.choice([2, 3]),
                    "country": "JP",
                    "plant": "豊浜工場",
                }
            )
        out["suppliers"] = pd.concat([out["suppliers"], pd.DataFrame(rows)], ignore_index=True)

    n_parts = _scaled(targets.get("parts", 350), scale, floor=10)
    if len(out["parts"]) < n_parts:
        rows = []
        for i in range(len(out["parts"]), n_parts):
            rows.append(
                {
                    "part_no": f"P-BG-{i:04d}",
                    "name": f"背景部品 {i}",
                    "category": rng.choice(["材料", "成形品", "サブ組立"]),
                    "material_spec": "-",
                    "supplier_id": "SUP-BG-004",
                }
            )
        out["parts"] = pd.concat([out["parts"], pd.DataFrame(rows)], ignore_index=True)

    n_insp = _scaled(targets.get("inspection_results", 400000), scale, floor=50)
    existing = len(out["inspection_results"])
    if existing < n_insp:
        rows = []
        lots = out["lots"]["lot_id"].tolist() if len(out["lots"]) else ["HC-2605-117"]
        bg_lots = [l for l in lots if not str(l).startswith("ML-")]
        pool = bg_lots or lots
        for i in range(existing, n_insp):
            lot = rng.choice(pool)
            usl, lsl = 0.15, 0.05
            val = lsl + (usl - lsl) * rng.uniform(0.45, 0.75)
            rows.append(
                {
                    "insp_id": f"INSP-BG-{i}",
                    "lot_id": lot,
                    "item": rng.choice(["歯形", "外径", "バックラッシ"]),
                    "value": val,
                    "lsl": lsl,
                    "usl": usl,
                    "judgment": "OK",
                }
            )
        out["inspection_results"] = pd.concat(
            [out["inspection_results"], pd.DataFrame(rows)], ignore_index=True
        )

    n_def = _scaled(targets.get("defects", 5000), scale, floor=5)
    if len(out["defects"]) < n_def:
        rows = []
        for i in range(len(out["defects"]), n_def):
            rows.append(
                {
                    "defect_id": f"DEF-BG-{i}",
                    "lot_id": rng.choice(out["lots"]["lot_id"].tolist() or ["HC-2605-117"]),
                    "defect_code": rng.choice(["外観その他", "寸法", "欠け"]),
                    "qty": 1,
                    "note": "背景",
                }
            )
        out["defects"] = pd.concat([out["defects"], pd.DataFrame(rows)], ignore_index=True)

    n_bom = _scaled(targets.get("bom", 900), scale, floor=5)
    if len(out["bom"]) < n_bom:
        parts = out["parts"]["part_no"].tolist()
        rows = []
        for i in range(len(out["bom"]), n_bom):
            p, c = rng.sample(parts, 2) if len(parts) >= 2 else (parts[0], parts[0])
            rows.append(
                {
                    "parent_part_no": p,
                    "child_part_no": c,
                    "qty_per": 1,
                    "valid_from": date(2024, 4, 1),
                    "valid_to": date(2026, 12, 31),
                }
            )
        out["bom"] = pd.concat([out["bom"], pd.DataFrame(rows)], ignore_index=True)

    return out
