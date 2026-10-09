"""Trino Iceberg カタログ名の解決 (LLM が ``ossie`` と誤るケースを補正)。"""
from __future__ import annotations

import os

# Apache Ossie / semantic YAML 用語。Trino カタログ名ではない。
_NON_TRINO_CATALOGS = frozenset(
    {
        "ossie",
        "semantic",
        "apache_ossie",
    }
)


def default_trino_catalog() -> str:
    """接続設定または env から既定 Iceberg カタログ名を返す。"""
    from solomon.transport.config import get_trino_config

    cfg = get_trino_config()
    if cfg and cfg.catalog:
        return cfg.catalog
    raw = (os.environ.get("SOLOMON_TRINO_CATALOG") or "iceberg").strip()
    return raw or "iceberg"


def resolve_trino_catalog(catalog: str | None) -> str:
    """Tool / Task 出力の catalog を Trino 向けに正規化する。"""
    default = default_trino_catalog()
    if catalog is None:
        return default
    text = str(catalog).strip()
    if not text:
        return default
    if text.lower() in _NON_TRINO_CATALOGS:
        return default
    return text


__all__ = ["default_trino_catalog", "resolve_trino_catalog"]
