"""Collect Ossie ``ai_context.examples`` (shared with router tests)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def collect_examples_from_model(path: Path) -> list[str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    items = raw.get("semantic_model")
    if items is None:
        models = [raw]
    elif isinstance(items, list):
        models = items
    else:
        models = [items]
    out: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        ai = model.get("ai_context")
        if isinstance(ai, dict):
            out.extend(str(x) for x in ai.get("examples") or [])
        for ds in model.get("datasets") or []:
            if not isinstance(ds, dict):
                continue
            dai = ds.get("ai_context")
            if isinstance(dai, dict):
                out.extend(str(x) for x in dai.get("examples") or [])
    return [q.strip() for q in out if q and str(q).strip()]


def all_examples(semantic_root: Path) -> list[str]:
    models_dir = semantic_root / "models"
    if not models_dir.is_dir():
        return []
    out: list[str] = []
    for path in sorted(models_dir.glob("*.yaml")) + sorted(models_dir.glob("*.yml")):
        out.extend(collect_examples_from_model(path))
    return out


__all__ = ["collect_examples_from_model", "all_examples"]
