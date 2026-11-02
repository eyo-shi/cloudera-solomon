"""文書 JSONL / doc_index / mentions 生成（template モード）。"""

from __future__ import annotations

import json
import random
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


def _has_forbidden(text: str, forbidden: list[str]) -> bool:
    return any(term in text for term in forbidden)


def _planted_body(doc_id: str, spec: dict[str, Any]) -> str:
    if doc_id == "QR-2024-0815":
        return (
            "8D QR-2024-0815 北見工場 PW ギア。現象: 噛み合い時の打音・コトコト。"
            "原因: ペレット吸湿。是正: 露点計の定期校正。D7 横展開: （未記入）"
        )
    if doc_id.startswith("DR-2025"):
        return "北見工場。コトコト音。乾燥やり直し実施。"
    if doc_id.startswith("DR-2026-0514"):
        return "7 号機ドライヤー露点高め。納期優先で乾燥 2.5h で立ち上げ。"
    must = spec.get("must_include") or []
    return "。".join(str(x) for x in must)


def generate_documents(
    scenario: dict[str, Any],
    *,
    scale: float,
    mode: str,
    rng: random.Random,
    cache_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict], list[dict]]:
    forbidden = scenario.get("forbidden_terms_planted_docs") or ["異音"]
    lex = scenario.get("generation_lexicon") or {}
    targets = scenario.get("doc_type_targets") or {}

    doc_index_rows: list[dict[str, Any]] = []
    docs_jsonl: list[dict] = []
    chunks_jsonl: list[dict] = []
    mentions_lot: list[dict] = []
    mentions_eq: list[dict] = []
    mentions_part: list[dict] = []

    for spec in scenario.get("planted_documents") or []:
        doc_id = spec["doc_id"]
        body = _planted_body(doc_id, spec)
        if _has_forbidden(body, forbidden):
            raise RuntimeError(f"planted doc {doc_id} contains forbidden term")
        doc_index_rows.append(
            {
                "doc_id": doc_id,
                "doc_type": spec.get("doc_type", "daily_report"),
                "doc_date": date(2026, 5, 14),
                "plant": spec.get("plant", "豊浜工場"),
                "equipment_id": spec.get("equipment_id"),
                "part_no": None,
                "lot_ids": ["HC-2605-117"],
                "title": doc_id,
            }
        )
        docs_jsonl.append({"doc_id": doc_id, "body": body, "title": doc_id})
        chunks_jsonl.append({"doc_id": doc_id, "chunk_id": f"{doc_id}#0", "section": "main", "text": body})
        if spec.get("equipment_id"):
            mentions_eq.append({"doc_id": doc_id, "entity_id": spec["equipment_id"]})
        mentions_lot.append({"doc_id": doc_id, "entity_id": "HC-2605-117"})

    def add_doc(doc_type: str, i: int, body: str, *, decoy: bool = False) -> None:
        doc_id = f"{doc_type}-{'dec' if decoy else 'bg'}-{i:05d}"
        doc_index_rows.append(
            {
                "doc_id": doc_id,
                "doc_type": doc_type if not decoy else "daily_report",
                "doc_date": date(2025, 1, 1) + timedelta(days=i % 900),
                "plant": rng.choice(["豊浜工場", "北見工場"]),
                "equipment_id": "M-07" if rng.random() < 0.5 else None,
                "part_no": rng.choice(["WH-200", "PG-310", None]),
                "lot_ids": [],
                "title": doc_id,
            }
        )
        docs_jsonl.append({"doc_id": doc_id, "body": body, "title": doc_id})
        chunks_jsonl.append({"doc_id": doc_id, "chunk_id": f"{doc_id}#0", "section": "main", "text": body})

    n_decoy = max(1, int((targets.get("decoy") or 400) * scale))
    decoy_terms = scenario["hidden_facts"]["H6"]["decoy_terms"]
    for i in range(n_decoy):
        term = rng.choice(decoy_terms)
        body = f"設備点検。{term}に関する報告。空調ブロワ・搬送コンベア・ブレーキ等。EPS 電気ノイズ調査。"
        add_doc("daily_report", i, body, decoy=True)

    for doc_type, count in targets.items():
        if doc_type == "decoy":
            continue
        n = max(1, int(count * scale)) if doc_type != "8d" else max(2, int(count * scale))
        if scale < 0.1 and doc_type in ("daily_report", "maintenance", "claim"):
            n = min(n, 20)
        existing = sum(1 for r in doc_index_rows if r["doc_type"] == doc_type)
        for i in range(existing, existing + n):
            sym = rng.choice(lex.get("symptoms") or ["打音"])
            body = f"背景 {doc_type} 記録。{sym}。通常操業。"
            stored_type = "oem_claim" if doc_type == "claim" else doc_type
            doc_id = f"{stored_type}-bg-{i:05d}"
            doc_index_rows.append(
                {
                    "doc_id": doc_id,
                    "doc_type": stored_type,
                    "doc_date": date(2025, 1, 1) + timedelta(days=i % 900),
                    "plant": rng.choice(["豊浜工場", "北見工場"]),
                    "equipment_id": "M-07" if rng.random() < 0.5 else None,
                    "part_no": rng.choice(["WH-200", "PG-310", None]),
                    "lot_ids": [],
                    "title": doc_id,
                }
            )
            docs_jsonl.append({"doc_id": doc_id, "body": body, "title": doc_id})
            chunks_jsonl.append(
                {"doc_id": doc_id, "chunk_id": f"{doc_id}#0", "section": "main", "text": body}
            )

    if mode == "llm":
        cache_dir.mkdir(parents=True, exist_ok=True)
        # LLM モードはキャッシュ未命中時のみ solomon LLM を呼ぶ（省略時 template と同じ）
        pass

    doc_index = pd.DataFrame(doc_index_rows)
    return (
        doc_index,
        pd.DataFrame(mentions_lot),
        pd.DataFrame(mentions_eq),
        pd.DataFrame(mentions_part),
        docs_jsonl,
        chunks_jsonl,
    )
