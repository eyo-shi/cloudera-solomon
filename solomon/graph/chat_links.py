"""Chat 回答 Markdown から Graph タブで Cypher を実行するリンク。"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode


def graph_cypher_markdown_link(
    cypher: str,
    params: dict[str, Any] | None = None,
    *,
    label: str = "参照 Cypher",
) -> str:
    """``[label](solomon://graph-cypher?...)`` — UI が中央 Graph タブで実行する。"""
    text = cypher.strip()
    if not text:
        return label
    payload: dict[str, str] = {"cypher": text}
    if params:
        payload["params"] = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    query = urlencode(payload)
    safe_label = label.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return f"[{safe_label}](solomon://graph-cypher?{query})"


__all__ = ["graph_cypher_markdown_link"]
