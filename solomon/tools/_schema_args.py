"""Trino / Iceberg Tool 引数の schema 正規化 (再エクスポート)。"""
from solomon.transport.schema_args import coalesce_schema_field, normalize_tool_kwargs

__all__ = ["coalesce_schema_field", "normalize_tool_kwargs"]
