"""Chat 回答 Markdown から Graph タブで Cypher を実行するリンク。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from solomon.markdown.solomon_links import solomon_markdown_link


def graph_cypher_markdown_link(
    cypher: str,
    params: dict[str, Any] | None = None,
    *,
    run_cypher: str | None = None,
    label: str = "参照 Cypher",
) -> str:
    """``[label](solomon://graph-cypher?...)`` — UI が中央 Graph タブで実行する。"""
    text = cypher.strip()
    if not text:
        return label
    payload: dict[str, str] = {"cypher": text}
    run_text = (run_cypher or "").strip()
    if run_text and run_text != text:
        payload["run"] = run_text
    if params:
        payload["params"] = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
        for key, val in params.items():
            if val not in (None, ""):
                payload[str(key)] = str(val)
    url_seed = json.dumps(payload, sort_keys=True)
    ref_suffix = hashlib.sha256(url_seed.encode()).hexdigest()[:10]
    return solomon_markdown_link(
        label,
        "graph-cypher",
        payload,
        ref_key=f"solomon-graph-cypher-{ref_suffix}",
    )


__all__ = ["graph_cypher_markdown_link"]
