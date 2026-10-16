"""System name inference helpers (legacy catalog / graph metadata)."""

from __future__ import annotations

import re
from typing import Any

_SYSTEM_META_KEYS = ("system", "system_name", "application", "app", "service")


def normalize_system_id(name: str) -> str:
    """System ノード id 用に正規化する。"""
    text = name.strip().lower()
    text = re.sub(r"[^a-z0-9_\-\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]+", "_", text)
    return text.strip("_") or "default"


def infer_system_name(
    *,
    key: str,
    schema: str,
    meta_kv: list[dict[str, Any]] | None = None,
    explicit: str | None = None,
) -> str:
    """S3 key / meta_kv / schema から System 名を推定する。"""
    if explicit and explicit.strip():
        return explicit.strip()

    for item in meta_kv or []:
        k = str(item.get("key", "")).lower()
        if k in _SYSTEM_META_KEYS and item.get("value"):
            return str(item["value"]).strip()

    if len(key.split("/")) >= 2:
        first = key.split("/")[0].strip()
        if first and not first.startswith("."):
            return first

    return schema.strip() or "default"


__all__ = [
    "normalize_system_id",
    "infer_system_name",
]
