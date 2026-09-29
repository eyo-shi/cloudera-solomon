"""Trino deployment mode and internal warehouse (DuckDB) helpers."""

from solomon.trino.mode import is_external_trino_mode, is_internal_trino_mode, trino_mode

__all__ = [
    "trino_mode",
    "is_internal_trino_mode",
    "is_external_trino_mode",
]
