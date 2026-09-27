"""Graph-oriented file ingest helpers for Router clarification."""

from __future__ import annotations

import re
from typing import Any

_GRAPH_INGEST_KEYWORDS = (
    "ナレッジグラフ",
    "知識グラフ",
    "グラフに追加",
    "グラフへ追加",
    "グラフDB",
    "neo4j",
    "knowledge graph",
    "graph ingest",
    "graphに追加",
)

_FIELD_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*")


def is_graph_ingest_request(prompt: str) -> bool:
    text = prompt.lower()
    return any(kw in prompt or kw in text for kw in _GRAPH_INGEST_KEYWORDS)


def _extract_identifiers(raw: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for match in _IDENTIFIER_RE.finditer(raw):
        name = match.group(0)
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def parse_node_fields(prompt: str) -> list[str] | None:
    """プロンプトからノード化するフィールド名を抽出する。"""
    text = re.sub(r"s3://[^\s]+", " ", prompt.strip())
    if not text:
        return None

    before_node = re.search(
        r"((?:[A-Za-z_][A-Za-z0-9_\-]*)(?:\s*[,、と・]\s*[A-Za-z_][A-Za-z0-9_\-]*)*)\s*を?\s*ノード",
        text,
    )
    if before_node:
        fields = _extract_identifiers(before_node.group(1))
        if fields:
            return fields

    after_node = re.search(
        r"ノード(?:に|として|にする|は)\s*(.+?)(?:\s|$|を|。)",
        text,
    )
    if after_node:
        fields = _extract_identifiers(after_node.group(1))
        if fields:
            return fields

    # 聞き返しへの短い回答 (例: "customer_id, product_name")
    if len(text) <= 200 and not is_graph_ingest_request(text):
        if re.fullmatch(r"[\w\-\s,、と・]+", text):
            fields = _extract_identifiers(text)
            if fields and all(_FIELD_TOKEN_RE.fullmatch(name) for name in fields):
                return fields
    return None


def build_graph_ingest_clarification(
    *,
    key: str,
    column_names: list[str] | None = None,
) -> str:
    filename = key.rsplit("/", 1)[-1] if key else key
    if column_names:
        joined = ", ".join(column_names[:30])
        suffix = " …" if len(column_names) > 30 else ""
        return (
            f"ファイル `{filename}` をナレッジグラフに追加します。\n\n"
            f"検出したフィールド: {joined}{suffix}\n\n"
            "どのフィールドをノードにしますか？ "
            "フィールド名をカンマ区切りで教えてください "
            "(例: customer_id, product_name)。"
        )
    return (
        f"ファイル `{filename}` をナレッジグラフに追加します。\n\n"
        "ファイル内のどのフィールドをノードにしますか？ "
        "フィールド名をカンマ区切りで教えてください "
        "(例: customer_id, product_name)。"
    )


def resolve_pending_graph_ingest(
    prompt: str, entity_memory: dict[str, Any]
) -> dict[str, Any] | None:
    """pending_graph_ingest + フィールド指定回答を INGEST 引数に解決する。"""
    pending = entity_memory.get("pending_graph_ingest")
    if not isinstance(pending, dict):
        return None
    bucket = pending.get("bucket")
    key = pending.get("key")
    if not bucket or not key:
        return None
    fields = parse_node_fields(prompt)
    if not fields:
        return None
    return {
        "bucket": str(bucket),
        "key": str(key),
        "target_schema": str(pending.get("target_schema") or "demo"),
        "graph_ingest": True,
        "node_fields": fields,
    }
