"""Chat 回答 Markdown から Search ドキュメントタブを開くリンク。"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode


def _escape_md_label(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


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
    query = urlencode(params)
    return f"[{_escape_md_label(label)}](solomon://search-document?{query})"


__all__ = ["search_document_markdown_link"]
