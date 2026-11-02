"""Ossie datatype → Trino 型。"""

from __future__ import annotations

from solomon.semantic.models import OssieField
from solomon.semantic.solomon_extension import extract_solomon_extensions


def physical_type(field: OssieField) -> str | None:
    for ext in field.custom_extensions or []:
        if getattr(ext, "vendor_name", "").upper() == "SOLOMON":
            data = extract_solomon_extensions([ext])
            pt = data.get("physical_type")
            if pt:
                return str(pt)
    return None


def trino_type(field: OssieField) -> str:
    dt = (field.datatype or "String").strip()
    if dt == "String":
        return "varchar"
    if dt == "Integer":
        return "bigint"
    if dt == "Int32":
        return "integer"
    if dt == "Decimal":
        return "decimal(18,4)"
    if dt == "Float":
        return "double"
    if dt == "Boolean":
        return "boolean"
    if dt == "Date":
        return "date"
    if dt == "DateTime":
        return "timestamp(6)"
    if dt == "DateTimeTz":
        return "timestamp(6) with time zone"
    if dt == "Timestamp":
        return "timestamp(6)"
    if dt == "Opaque":
        pt = (physical_type(field) or "").lower()
        if "array" in pt:
            return "array(varchar)"
        if "varchar" in pt:
            return "varchar"
        return "varchar"
    return "varchar"


def create_table_ddl(fq: str, fields: list[OssieField]) -> str:
    cols = ",\n  ".join(f"{f.name} {trino_type(f)}" for f in fields)
    return f"CREATE TABLE IF NOT EXISTS {fq} (\n  {cols}\n)"


__all__ = ["trino_type", "create_table_ddl", "physical_type"]
