"""文書 JSONL / doc_index / mentions 生成（template モード）。

- 仕込み文書は scenario.yaml の planted_documents が正（本文・日付・設備・ロット）。
  must_include / must_exclude を検証し、外れたら生成を止める。
- デコイ（H6）は全件「異音」を含む別件の記録（空調・搬送・ブレーキ試験等）。
- 背景文書は 2025-01-01〜2026-10-31 の通常記録。事件の手掛かり語
  （ゴトゴト・ガタ・樹脂ギア・2.5h・露点高め）は使わない。
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

DOC_START = date(2025, 1, 1)
DOC_END = date(2026, 10, 31)
D07_WINDOW = (date(2026, 5, 12), date(2026, 5, 26))
MACHINES = [f"M-{n:02d}" for n in range(1, 13)]
DRYERS = [f"D-{n:02d}" for n in range(1, 13)]
LINES = ["L-A200", "L-A210", "L-P55"]
PARTS = ["WH-200", "WH-210", "PG-310", "PG-320", "GR-150", "CL-80", "HS-40"]
UNIT_PARTS = ["EPS-A200", "EPS-A210", "PWR-55"]

PREFIX = {
    "daily_report": "DR",
    "maintenance": "MT",
    "8d": "QR",
    "defect_report": "DF",
    "oem_claim": "CL",
    "fmea": "FM",
    "change_notice": "CN",
}


def _has_forbidden(text: str, forbidden: list[str]) -> bool:
    return any(term in text for term in forbidden)


def _rand_date(rng: random.Random) -> date:
    return DOC_START + timedelta(days=rng.randint(0, (DOC_END - DOC_START).days))


def _machine(rng: random.Random, when: date) -> str:
    pool = MACHINES
    if D07_WINDOW[0] - timedelta(days=3) <= when <= D07_WINDOW[1] + timedelta(days=3):
        pool = [m for m in MACHINES if m != "M-07"]
    return rng.choice(pool)


def _dryer(rng: random.Random, when: date) -> str:
    pool = DRYERS
    if D07_WINDOW[0] - timedelta(days=3) <= when <= D07_WINDOW[1] + timedelta(days=3):
        pool = [d for d in DRYERS if d != "D-07"]
    return rng.choice(pool)


def _bg_body(doc_type: str, d: date, rng: random.Random) -> tuple[str, str, str | None, str | None, str]:
    """(title, body, equipment_id, part_no, plant) を返す。"""
    plant = "豊浜工場" if rng.random() < 0.85 else "北見工場"
    if doc_type == "daily_report":
        m = _machine(rng, d)
        part = rng.choice(PARTS)
        shift = rng.choice(["A", "B"])
        event = rng.choice(
            [
                "計画通り生産、外観・寸法 OK",
                "段取り替え 40 分。初品確認 OK",
                "金型温度を調整後、良品を確認",
                "休憩後の立ち上げで寸法再確認、問題なし",
                "ショート 2 個発生、射出圧を微調整",
                "取出しロボットのチャック位置を再ティーチング",
                "材料切替、パージ後に初品確認 OK",
            ]
        )
        return (
            f"作業日報 {d} 成形 {shift} 班",
            f"作業日報 {d} {plant} 成形 {shift} 班。\n成形機 {int(m[2:])} 号で {part} を生産。{event}。",
            m,
            part,
            plant,
        )
    if doc_type == "maintenance":
        eq = rng.choice([_machine(rng, d), _dryer(rng, d), rng.choice(LINES)])
        action = rng.choice(
            [
                "定期点検、異常なし",
                "ヒーターバンド交換",
                "フィルタ清掃",
                "油圧ホース交換",
                "ノズル清掃と温度センサ確認",
                "ボールねじ給脂",
                "安全扉スイッチ交換",
                "ホッパー内清掃",
            ]
        )
        return (f"保全記録 {d} {eq}", f"保全記録 {d} {eq}（{plant}）。\n{action}。", eq, None, plant)
    if doc_type == "8d":
        part = rng.choice(PARTS + UNIT_PARTS)
        phen = rng.choice(["ブラケットの割れ", "コネクタ嵌合不良", "ラベル貼り間違い", "外径寸法ばらつき", "バリ残り", "梱包破損"])
        cause = rng.choice(["金型摩耗", "作業手順の逸脱", "治具の位置ずれ", "検査治具の校正切れ", "梱包仕様の誤り"])
        return (
            f"8D {part} {phen}",
            f"8D レポート（{plant} / {part}）\nD2 現象: {phen}。\nD4 真因: {cause}。\nD5/D6 恒久対策: 標準書改訂と教育。\nD7 横展開: 類似工程へ展開済み。",
            None,
            part,
            plant,
        )
    if doc_type == "defect_report":
        part = rng.choice(PARTS)
        code, note = rng.choice([("寸法", "外径公差外れ"), ("欠け", "ゲート部欠け"), ("バリ", "パーティング部バリ"), ("ショート", "充填不足"), ("ヒケ", "リブ部ヒケ")])
        return (f"不具合報告 {part} {code}", f"不具合報告（{plant}）{part}: {code}。{note}。選別済み、流出なし。", _machine(rng, d), part, plant)
    if doc_type == "oem_claim":
        model, part = rng.choice([("CV-3", "EPS-A210"), ("KX-1", "EPS-A210"), ("VN-7", "PWR-55")])
        sym = rng.choice(["警告灯点灯", "ドア下部から雨漏り", "ブレーキ鳴き", "高速走行時の風切り音", "ウィンドウ昇降が遅い", "ステアリングが重い"])
        verdict = rng.choice(["調査中", "当社責任なし（車両側要因）", "部品交換で解消"])
        return (f"OEM クレーム {model} {sym}", f"OEM クレーム連絡 {model}（{part}）: {sym}。判定: {verdict}。", None, part, "豊浜工場")
    if doc_type == "fmea":
        part = rng.choice(PARTS)
        mode, cause = rng.choice(
            [
                ("歯面摩耗", "材料吸湿による強度低下（乾燥条件の管理で予防）"),
                ("割れ", "ウェルドライン強度不足"),
                ("寸法不良", "金型温度ばらつき"),
                ("変形", "取出し時の応力"),
            ]
        )
        return (f"FMEA {part} {mode}", f"FMEA {part}: 故障モード {mode}。原因: {cause}。RPN {rng.randint(40, 160)}。", None, part, "豊浜工場")
    # change_notice
    part = rng.choice(PARTS + UNIT_PARTS)
    change = rng.choice(["金型メンテナンスに伴う型番変更", "作業者の配置変更", "検査治具の更新", "梱包材の仕様変更", "成形条件の微調整（保圧時間）"])
    return (f"4M 変更連絡 {part}", f"4M 変更連絡 {part}: {change}。初物確認 OK、OEM 承認不要。", None, part, plant)


DECOY_SUBJECTS = [
    ("空調ブロワ", "ベアリング交換で解消"),
    ("搬送コンベア", "チェーン張りを調整"),
    ("集塵機", "ダクト固定ボルトの増し締め"),
    ("冷却塔ポンプ", "インペラ清掃"),
    ("コンプレッサ", "吸気フィルタ交換"),
    ("ブレーキ試験台", "試験治具の緩みを修正"),
    ("フォークリフト", "マスト給脂"),
    ("EPS 評価台", "電気ノイズ対策でアース線を追加"),
]


def generate_documents(
    scenario: dict[str, Any],
    *,
    scale: float,
    mode: str,
    rng: random.Random,
    cache_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict], list[dict]]:
    forbidden = scenario.get("forbidden_terms_planted_docs") or ["異音"]
    targets = scenario.get("doc_type_targets") or {}
    decoy_terms = scenario["hidden_facts"]["H6"]["decoy_terms"]

    doc_index_rows: list[dict[str, Any]] = []
    docs_jsonl: list[dict] = []
    chunks_jsonl: list[dict] = []
    mentions_lot: list[dict] = []
    mentions_eq: list[dict] = []
    mentions_part: list[dict] = []
    used_ids: set[str] = set()

    def add(
        doc_id: str,
        doc_type: str,
        d: date,
        plant: str,
        equipment_id: str | None,
        part_no: str | None,
        lot_ids: list[str],
        title: str,
        body: str,
    ) -> None:
        if doc_id in used_ids:
            raise RuntimeError(f"duplicate doc_id {doc_id}")
        used_ids.add(doc_id)
        meta = {
            "doc_id": doc_id,
            "doc_type": doc_type,
            "doc_date": d,
            "plant": plant,
            "equipment_id": equipment_id,
            "part_no": part_no,
            "lot_ids": list(lot_ids),
            "title": title,
        }
        doc_index_rows.append(meta)
        docs_jsonl.append({**meta, "body": body})
        chunks_jsonl.append({**meta, "chunk_id": f"{doc_id}#0", "section": "main", "text": body})
        if equipment_id:
            mentions_eq.append({"doc_id": doc_id, "entity_id": equipment_id})
            if equipment_id.startswith("D-"):
                mentions_eq.append({"doc_id": doc_id, "entity_id": "M-" + equipment_id[2:]})
        if part_no:
            mentions_part.append({"doc_id": doc_id, "entity_id": part_no})
        for lot in lot_ids:
            mentions_lot.append({"doc_id": doc_id, "entity_id": lot})

    # --- 仕込み文書 ---
    for spec in scenario.get("planted_documents") or []:
        doc_id = spec["doc_id"]
        body = str(spec["body"]).strip()
        excl = list(spec.get("must_exclude") or []) + list(forbidden)
        if _has_forbidden(body, excl):
            raise RuntimeError(f"planted doc {doc_id} contains a forbidden term")
        missing = [t for t in spec.get("must_include") or [] if str(t) not in body]
        if missing:
            raise RuntimeError(f"planted doc {doc_id} misses {missing}")
        add(
            doc_id,
            spec.get("doc_type", "daily_report"),
            date.fromisoformat(str(spec["doc_date"])),
            spec.get("plant", "豊浜工場"),
            spec.get("equipment_id"),
            spec.get("part_no"),
            list(spec.get("lot_ids") or []),
            spec.get("title") or doc_id,
            body,
        )

    seq: dict[str, int] = {}

    def next_id(doc_type: str, d: date) -> str:
        key = f"{PREFIX[doc_type]}-{d:%Y-%m%d}"
        seq[key] = seq.get(key, 0) + 1
        return f"{key}-{seq[key]:02d}"

    # --- デコイ（H6: すべて「異音」を含む）---
    n_decoy = max(1, int(round((targets.get("decoy") or 400) * scale)))
    for _ in range(n_decoy):
        d = _rand_date(rng)
        subject, fix = rng.choice(DECOY_SUBJECTS)
        extra = rng.choice([t for t in decoy_terms if t != "異音"] or ["異音"])
        doc_type = rng.choice(["daily_report", "maintenance"])
        plant = "豊浜工場" if rng.random() < 0.8 else "北見工場"
        body = f"{'作業日報' if doc_type == 'daily_report' else '保全記録'} {d} {plant}。\n{subject}から異音（{extra}あり）。{fix}。生産への影響なし。"
        add(next_id(doc_type, d), doc_type, d, plant, None, None, [], f"{subject} 異音対応 {d}", body)

    # --- 背景文書 ---
    for key, count in targets.items():
        if key == "decoy":
            continue
        doc_type = "oem_claim" if key == "claim" else key
        floor = 2 if doc_type == "8d" else 1
        n = max(floor, int(round(count * scale)))
        for _ in range(n):
            d = _rand_date(rng)
            title, body, eq, part, plant = _bg_body(doc_type, d, rng)
            add(next_id(doc_type, d), doc_type, d, plant, eq, part, [], title, body)

    if mode == "llm":
        cache_dir.mkdir(parents=True, exist_ok=True)
        # LLM モードは未実装（template と同じ本文を使う）

    return (
        pd.DataFrame(doc_index_rows),
        pd.DataFrame(mentions_lot),
        pd.DataFrame(mentions_eq),
        pd.DataFrame(mentions_part),
        docs_jsonl,
        chunks_jsonl,
    )
