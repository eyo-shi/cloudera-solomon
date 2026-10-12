"""Chat 回答 Markdown から Search ドキュメントタブを開くリンク。"""
from __future__ import annotations

import hashlib
from typing import Any

from solomon.markdown.solomon_links import _escape_md_label, solomon_markdown_link


def search_document_markdown_link(label: str, doc: dict[str, Any]) -> str:
    """``[label](solomon://search-document?...)`` — UI が中央ペインで payload を開く。"""
    key = str(doc.get("object_key") or "").strip()
    if not key:
        return _escape_md_label(label)
    params: dict[str, str] = {"object_key": key}
    for field in ("format", "trace_id", "index", "vb_machine_no"):
        val = doc.get(field)
        if val not in (None, ""):
            params[field] = str(val)
    ref_suffix = hashlib.sha256(key.encode()).hexdigest()[:10]
    return solomon_markdown_link(
        label,
        "search-document",
        params,
        ref_key=f"solomon-search-doc-{ref_suffix}",
    )


__all__ = ["search_document_markdown_link"]
