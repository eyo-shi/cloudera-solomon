"""SOLOMON vendor ``custom_extensions`` のパースと正規化。"""

from __future__ import annotations

import json
from typing import Any, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

VENDOR = "SOLOMON"
KNOWN_TOP_LEVEL_KEYS = frozenset(
    {
        "version",
        "glossary",
        "tool_hints",
        "graph_examples",
        "search",
        "verified_queries",
        "answer",
        "kind",
        "queryable",
        "graph",
        "document_index",
        "filterable",
        "physical_type",
    }
)


class SolomonExtensionError(Exception):
    pass


def _parse_data_payload(data: Any) -> dict[str, Any]:
    if data is None or data == "":
        return {}
    if isinstance(data, dict):
        return dict(data)
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            try:
                parsed = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                raise SolomonExtensionError(f"invalid SOLOMON extension data: {exc}") from exc
        if not isinstance(parsed, dict):
            raise SolomonExtensionError("SOLOMON extension data must be a JSON object")
        return parsed
    raise SolomonExtensionError(f"unsupported extension data type: {type(data)}")


def normalize_extension_data(data: Any) -> str:
    """本家準拠の JSON 文字列に正規化する。"""
    obj = _parse_data_payload(data)
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def parse_solomon_extension(data: Any, *, warn_unknown: bool = True) -> dict[str, Any]:
    obj = _parse_data_payload(data)
    if warn_unknown:
        for key in obj:
            if key not in KNOWN_TOP_LEVEL_KEYS:
                pass  # validate CLI で警告
    return obj


def extract_solomon_extensions(
    extensions: list[Any] | None,
) -> dict[str, Any]:
    if not extensions:
        return {}
    for ext in extensions:
        vendor = getattr(ext, "vendor_name", None) or (
            ext.get("vendor_name") if isinstance(ext, dict) else None
        )
        if str(vendor).upper() != VENDOR:
            continue
        raw_data = getattr(ext, "data", None) if not isinstance(ext, dict) else ext.get("data")
        return parse_solomon_extension(raw_data, warn_unknown=False)
    return {}


class GlossaryEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    term: str
    description: str = ""
    synonyms: list[str] = Field(default_factory=list)


def glossary_from_extension(ext: dict[str, Any]) -> list[GlossaryEntry]:
    raw = ext.get("glossary") or []
    out: list[GlossaryEntry] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict) and item.get("term"):
            out.append(GlossaryEntry.model_validate(item))
    return out


__all__ = [
    "VENDOR",
    "KNOWN_TOP_LEVEL_KEYS",
    "SolomonExtensionError",
    "extract_solomon_extensions",
    "glossary_from_extension",
    "normalize_extension_data",
    "parse_solomon_extension",
]
