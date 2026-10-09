"""Trino / Iceberg Tool 引数の schema 正規化 (transport 層 — tool_base から参照)。"""
from __future__ import annotations

from typing import Any


def coalesce_schema_field(data: Any) -> Any:
    """LLM が target_schema を渡して schema を省略した場合に補完する。"""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    if not out.get("schema"):
        for alt in ("target_schema", "schema_name", "trino_schema", "schema_"):
            if out.get(alt):
                out["schema"] = out[alt]
                break
    return out


def normalize_tool_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """CrewAI Tool 呼び出し kwargs を run() シグネチャ向けに正規化する。"""
    return coalesce_schema_field(dict(kwargs))


__all__ = ["coalesce_schema_field", "normalize_tool_kwargs"]
