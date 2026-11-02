"""Ossie モデルからテーブル列定義を読む（列の二重定義を避ける）。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from solomon.semantic.models import OssieDataset, OssieField
from solomon.semantic.solomon_extension import extract_solomon_extensions
from solomon.semantic.store import load_models


def _physical_type(field: OssieField) -> str | None:
    for ext in field.custom_extensions or []:
        if getattr(ext, "vendor_name", "").upper() == "SOLOMON":
            data = extract_solomon_extensions([ext])
            pt = data.get("physical_type")
            if pt:
                return str(pt)
    return None


def ossie_to_pyarrow(field: OssieField) -> str:
    dt = (field.datatype or "String").lower()
    if dt == "opaque":
        pt = _physical_type(field) or ""
        if "array" in pt:
            return "list"
        return "string"
    mapping = {
        "string": "string",
        "int32": "int32",
        "int64": "int64",
        "decimal": "float64",
        "double": "float64",
        "float": "float64",
        "date": "date32",
        "timestamp": "timestamp[us]",
        "boolean": "bool",
    }
    return mapping.get(dt, "string")


def load_dataset_schemas(semantic_root: Path) -> dict[str, list[dict[str, Any]]]:
    os.environ["SOLOMON_SEMANTIC_ROOT"] = str(semantic_root.resolve())
    load_models(force=True)
    out: dict[str, list[dict[str, Any]]] = {}
    for model in load_models():
        for ds in model.datasets:
            cols: list[dict[str, Any]] = []
            for f in ds.fields:
                cols.append(
                    {
                        "name": f.name,
                        "datatype": f.datatype or "String",
                        "pyarrow": ossie_to_pyarrow(f),
                        "physical_type": _physical_type(f),
                    }
                )
            out[ds.name] = cols
    return out


def table_names(semantic_root: Path) -> list[str]:
    return list(load_dataset_schemas(semantic_root).keys())


__all__ = ["load_dataset_schemas", "ossie_to_pyarrow", "table_names"]
