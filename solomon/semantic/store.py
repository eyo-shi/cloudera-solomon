"""Ossie 本家形式モデルの読込 (<root>/models/*.yaml)。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import ValidationError

from solomon.semantic.models import (
    OssieDataset,
    OssieSemanticModel,
    dataset_fq_name,
    parse_models_from_yaml,
)
from solomon.semantic.search import dataset_search_terms, rank_datasets
from solomon.transport.errors import ErrorCode, err, ok
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

_cache_mtime: float = 0.0
_cache_models: list[OssieSemanticModel] = []
_cache_index: dict[str, tuple[OssieSemanticModel, OssieDataset, str]] = {}


def semantic_root() -> Path:
    root = os.environ.get("SOLOMON_SEMANTIC_ROOT", "./semantic")
    return Path(root).expanduser().resolve()


def _models_dir(root: Path) -> Path:
    return root / "models"


def _allowed_model_names() -> Optional[frozenset[str]]:
    raw = os.environ.get("SOLOMON_SEMANTIC_MODELS", "").strip()
    if not raw:
        return None
    names = {p.strip() for p in raw.split(",") if p.strip()}
    return frozenset(names) if names else None


def _latest_mtime(root: Path) -> float:
    models_dir = _models_dir(root)
    if not models_dir.is_dir():
        return 0.0
    latest = 0.0
    for path in models_dir.glob("*.yaml"):
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    for path in models_dir.glob("*.yml"):
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


def _rebuild_index(models: list[OssieSemanticModel]) -> dict[str, tuple[OssieSemanticModel, OssieDataset, str]]:
    index: dict[str, tuple[OssieSemanticModel, OssieDataset, str]] = {}
    for model in models:
        for ds in model.datasets:
            fq = dataset_fq_name(model.name, ds)
            index[fq.lower()] = (model, ds, fq)
            index[f"{model.name}.{ds.name}".lower()] = (model, ds, fq)
            index[ds.name.lower()] = (model, ds, fq)
    return index


def load_models(*, force: bool = False) -> list[OssieSemanticModel]:
    global _cache_mtime, _cache_models, _cache_index
    root = semantic_root()
    mtime = _latest_mtime(root)
    if not force and mtime == _cache_mtime and _cache_models:
        return _cache_models

    allowed = _allowed_model_names()
    models: list[OssieSemanticModel] = []
    models_dir = _models_dir(root)
    if models_dir.is_dir():
        paths = sorted(list(models_dir.glob("*.yaml")) + list(models_dir.glob("*.yml")))
        for path in paths:
            try:
                with path.open("r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh)
                for model in parse_models_from_yaml(raw):
                    if allowed is not None and model.name not in allowed:
                        continue
                    models.append(model)
            except (yaml.YAMLError, ValidationError, ValueError) as exc:
                _logger.warning("semantic.load_failed", path=str(path), error=str(exc))

    _cache_mtime = mtime
    _cache_models = models
    _cache_index = _rebuild_index(models)
    return models


def list_datasets() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    root = semantic_root()
    for model in load_models():
        for ds in model.datasets:
            fq = dataset_fq_name(model.name, ds)
            out.append(
                {
                    "model": model.name,
                    "name": ds.name,
                    "fq_name": fq,
                    "description": (ds.description or "")[:500],
                    "path": f"models/{model.name}.yaml",
                }
            )
    out.sort(key=lambda x: x["fq_name"])
    return out


def _relationships_for_dataset(
    model: OssieSemanticModel, dataset: OssieDataset
) -> list[dict[str, Any]]:
    rels: list[dict[str, Any]] = []
    ds_name = dataset.name
    for rel in model.relationships:
        from_name = rel.from_ or ""
        to_name = rel.to or ""
        if from_name == ds_name or to_name == ds_name:
            rels.append(rel.model_dump(by_alias=True, exclude_none=True))
    return rels


def read_dataset(name_or_fq: str) -> dict[str, Any]:
    key = (name_or_fq or "").strip().lower()
    if not key:
        return err(ErrorCode.OSSIE_NOT_FOUND, "dataset key is empty")
    load_models()
    hit = _cache_index.get(key)
    if hit is None and key.count(".") == 2:
        hit = _cache_index.get(key)
    if hit is None:
        return err(ErrorCode.OSSIE_NOT_FOUND, f"Ossie dataset not found: {name_or_fq}")
    model, ds, fq = hit
    return ok(
        {
            "model": model.name,
            "fq_name": fq,
            "dataset": ds.model_dump(by_alias=True, exclude_none=True),
            "relationships": _relationships_for_dataset(model, ds),
            "model_description": model.description,
        }
    )


def search_datasets(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    entries: list[tuple[dict[str, Any], list[str]]] = []
    for model in load_models():
        for ds in model.datasets:
            fq = dataset_fq_name(model.name, ds)
            meta = {
                "model": model.name,
                "name": ds.name,
                "fq_name": fq,
            }
            entries.append((meta, dataset_search_terms(model, ds)))
    ranked = rank_datasets(query, entries, top_k=top_k)
    out: list[dict[str, Any]] = []
    for score, meta in ranked:
        full = read_dataset(meta["fq_name"])
        if full.get("status") != "ok":
            continue
        out.append(
            {
                **meta,
                "score": round(score, 4),
                "dataset": full["dataset"],
                "relationships": full.get("relationships", []),
            }
        )
    return out


def semantic_generation() -> float:
    """モデルファイルの最新 mtime (キャッシュ無効化用)。"""
    return _latest_mtime(semantic_root())


__all__ = [
    "load_models",
    "list_datasets",
    "read_dataset",
    "search_datasets",
    "semantic_root",
    "semantic_generation",
]
