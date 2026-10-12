"""Markdown から Solomon UI 深リンク (solomon://) を生成する共通ヘルパ。"""
from __future__ import annotations

import hashlib
from urllib.parse import urlencode


def _escape_md_label(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def solomon_markdown_link(
    label: str,
    scheme_path: str,
    params: dict[str, str],
    *,
    ref_key: str | None = None,
) -> str:
    """``[label](solomon://...)`` または reference 形式（URL が長い場合）。"""
    safe_label = _escape_md_label(label)
    if not params:
        return safe_label
    query = urlencode(params)
    url = f"solomon://{scheme_path}?{query}"
    if len(url) <= 480 and ref_key is None:
        return f"[{safe_label}]({url})"
    digest = hashlib.sha256(url.encode()).hexdigest()[:10]
    ref_id = ref_key or f"solomon-{scheme_path.replace('/', '-')}-{digest}"
    return f"[{safe_label}][{ref_id}]\n\n[{ref_id}]: {url}"
