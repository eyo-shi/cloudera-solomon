"""Ossie ドメイン読込・検証。"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from solomon.semantic.models import OssieDataset, OssieField, OssieSemanticModel, dataset_source_ref
from solomon.semantic.solomon_extension import extract_solomon_extensions
from solomon.semantic.store import load_models


@dataclass
class TableSpec:
    name: str
    catalog: str
    schema: str
    table: str
    fq: str
    fields: list[OssieField]
    primary_key: list[str]
    kind: str
    queryable: bool
    graph: dict[str, Any] = field(default_factory=dict)
    document_index: dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainModel:
    domain_dir: Path
    semantic_root: Path
    model: OssieSemanticModel
    tables: dict[str, TableSpec]

    @property
    def domain_name(self) -> str:
        return self.model.name


def _parse_fq(source: str) -> tuple[str, str, str]:
    parts = source.split(".")
    if len(parts) != 3:
        raise ValueError(f"expected catalog.schema.table, got {source!r}")
    return parts[0], parts[1], parts[2]


def validate_semantic_root(semantic_root: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "solomon.semantic",
            "validate",
            "--root",
            str(semantic_root),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"semantic validate failed:\n{proc.stdout}\n{proc.stderr}"
        )


def load_domain(domain_dir: Path, *, validate: bool = True) -> DomainModel:
    domain_dir = domain_dir.expanduser().resolve()
    semantic_root = domain_dir / "semantic"
    if validate:
        validate_semantic_root(semantic_root)
    os.environ["SOLOMON_SEMANTIC_ROOT"] = str(semantic_root)
    os.environ["SOLOMON_SEMANTIC_MODELS"] = ""
    models = load_models(force=True)
    if not models:
        raise RuntimeError(f"no models under {semantic_root}")
    model = models[0]
    tables: dict[str, TableSpec] = {}
    for ds in model.datasets:
        ref = dataset_source_ref(ds.source)
        if not ref:
            continue
        cat, sch, tbl = _parse_fq(ref)
        ext = extract_solomon_extensions(ds.custom_extensions)
        pk = ds.primary_key
        if isinstance(pk, str):
            pk_list = [pk]
        elif isinstance(pk, list):
            pk_list = [str(x) for x in pk]
        else:
            pk_list = []
        tables[ds.name] = TableSpec(
            name=ds.name,
            catalog=cat,
            schema=sch,
            table=tbl,
            fq=ref,
            fields=list(ds.fields),
            primary_key=pk_list,
            kind=str(ext.get("kind") or "table"),
            queryable=ext.get("queryable", ext.get("kind") == "table"),
            graph=dict(ext.get("graph") or {}),
            document_index=dict(ext.get("document_index") or {}),
        )
    return DomainModel(domain_dir=domain_dir, semantic_root=semantic_root, model=model, tables=tables)


def field_names(spec: TableSpec) -> set[str]:
    return {f.name for f in spec.fields}


__all__ = ["DomainModel", "TableSpec", "load_domain", "validate_semantic_root"]
