"""Iceberg 取り込み先テーブル・新規/既存の Router 聞き返し。"""

from __future__ import annotations

import re
from typing import Any

_FQ_TABLE_RE = re.compile(
    r"(?:iceberg\.)?(?P<schema>[a-z][a-z0-9_]*)\.(?P<table>[a-z][a-z0-9_]*)",
    re.IGNORECASE,
)
_TABLE_NAME_RE = re.compile(
    r"(?:テーブル名|table\s*name?)[:：\s]+([a-z][a-z0-9_]*)",
    re.IGNORECASE,
)
_BARE_TABLE_RE = re.compile(
    r"(?:^|[\s、,])([a-z][a-z0-9_]{2,})(?:\s+という名前|\s+で新規|\s+に取り込)",
    re.IGNORECASE,
)

_CREATE_KW = (
    "新規作成",
    "新規で",
    "新規",
    "テーブルを作成",
    "テーブル作成",
    "create new",
    "create table",
    "作って",
    "作成して",
)
_APPEND_KW = (
    "既存",
    "既にある",
    "追加",
    "append",
    "上書きしない",
    "load into",
)


def prompt_specifies_table(prompt: str) -> bool:
    """プロンプトに投入先 fq / schema.table が明示されているか。"""
    if _FQ_TABLE_RE.search(prompt):
        return True
    if _TABLE_NAME_RE.search(prompt):
        return True
    return False


def build_ingest_target_clarification(
    *,
    key: str,
    failure_message: str | None = None,
    attempted_fq: str | None = None,
) -> str:
    filename = key.rsplit("/", 1)[-1] if key else key
    lines = [
        f"ファイル `{filename}` を Iceberg (Lakehouse) に取り込みます。",
        "",
        "次を教えてください。",
        "",
        "1. **どのテーブルに入れますか？**",
        "   - 例: `demo.quality_inspection`（スキーマ.テーブル名）",
        "   - または `iceberg.demo.quality_inspection`（カタログ付き）",
        "",
        "2. **テーブルがまだ無い場合**",
        "   - **新規作成**してデータを入れる",
        "   - それとも **既存テーブル**に追加する（既存の場合は fq を指定）",
        "",
        "回答例:",
        "- `demo.quality_kanken という名前で新規作成`",
        "- `iceberg.demo.existing_orders に既存テーブルとして追加`",
    ]
    if attempted_fq or failure_message:
        lines.insert(2, "**前回の取り込みは Iceberg テーブル作成の段階で失敗しました。**")
        if attempted_fq:
            lines.insert(3, f"- 試行していたテーブル: `{attempted_fq}`")
        if failure_message:
            lines.insert(
                4 if attempted_fq else 3,
                f"- 詳細: {failure_message[:500]}",
            )
        lines.insert(5 if attempted_fq and failure_message else 4, "")
    return "\n".join(lines)


def parse_ingest_target_reply(prompt: str) -> dict[str, Any] | None:
    """聞き返しへの回答から schema / table / create_new を抽出。"""
    text = prompt.strip()
    if not text:
        return None

    target_schema = "demo"
    proposed_table_name: str | None = None
    create_new: bool | None = None

    m = _FQ_TABLE_RE.search(text)
    if m:
        target_schema = m.group("schema").lower()
        proposed_table_name = m.group("table").lower()

    tm = _TABLE_NAME_RE.search(text)
    if tm:
        proposed_table_name = tm.group(1).lower()

    if not proposed_table_name:
        bm = _BARE_TABLE_RE.search(text)
        if bm:
            proposed_table_name = bm.group(1).lower()

    lower = text.lower()
    if any(kw in text or kw in lower for kw in _CREATE_KW):
        create_new = True
    if any(kw in text or kw in lower for kw in _APPEND_KW):
        create_new = False if create_new is None else create_new

    if proposed_table_name is None and create_new is None:
        return None

    out: dict[str, Any] = {"target_schema": target_schema}
    if proposed_table_name:
        out["proposed_table_name"] = proposed_table_name
    if create_new is not None:
        out["create_new_table"] = create_new
    return out


def resolve_pending_table_ingest(
    prompt: str, entity_memory: dict[str, Any]
) -> dict[str, Any] | None:
    """pending_table_ingest + ユーザー回答を INGEST 引数に解決。"""
    pending = entity_memory.get("pending_table_ingest")
    if not isinstance(pending, dict):
        return None
    bucket = pending.get("bucket")
    key = pending.get("key")
    if not bucket or not key:
        return None

    parsed = parse_ingest_target_reply(prompt)
    if parsed is None:
        return None

    args: dict[str, Any] = {
        "bucket": str(bucket),
        "key": str(key),
        "target_schema": str(parsed.get("target_schema") or pending.get("target_schema") or "demo"),
    }
    if pending.get("graph_ingest"):
        args["graph_ingest"] = True
        if pending.get("node_fields"):
            args["node_fields"] = pending["node_fields"]
    if parsed.get("proposed_table_name"):
        args["proposed_table_name"] = parsed["proposed_table_name"]
    if parsed.get("create_new_table") is not None:
        args["create_new_table"] = bool(parsed["create_new_table"])
    return args


def extract_attempted_fq_from_message(message: str) -> str | None:
    m = re.search(r"Iceberg テーブル\s+(iceberg\.\S+)\s+の作成", message)
    if m:
        return m.group(1)
    m = re.search(r"(iceberg\.[a-z0-9_]+\.[a-z0-9_]+)", message, re.I)
    return m.group(1) if m else None
