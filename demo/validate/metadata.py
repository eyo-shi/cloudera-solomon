"""Run metadata for reproducibility (models, analyzer, Ossie hash)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def ossie_models_hash(semantic_root: Path) -> str:
    models_dir = semantic_root / "models"
    h = hashlib.sha256()
    if not models_dir.is_dir():
        return ""
    for path in sorted(models_dir.glob("*.yaml")) + sorted(models_dir.glob("*.yml")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def collect_run_metadata(domain_dir: Path) -> dict[str, Any]:
    semantic_root = domain_dir / "semantic"
    meta: dict[str, Any] = {
        "ossie_hash": ossie_models_hash(semantic_root),
        "python": sys.version.split()[0],
    }
    try:
        from solomon.transport.config import get_opensearch_config

        cfg = get_opensearch_config()
        if cfg:
            meta["opensearch_docs_index"] = getattr(cfg, "docs_index_name", None)
            meta["opensearch_analyzer"] = getattr(cfg, "docs_analyzer", None)
            meta["embedding_dim"] = getattr(cfg, "embedding_dim", None)
            meta["embedding_model"] = os.environ.get("SOLOMON_LLM_EMBEDDING_MODEL") or os.environ.get(
                "LITELLM_EMBEDDING_MODEL"
            )
    except Exception:  # noqa: BLE001
        pass
    try:
        from solomon.opensearch.query_expansion import doc_search_expansion_enabled

        meta["doc_search_expansion_default"] = doc_search_expansion_enabled()
    except Exception:  # noqa: BLE001
        pass
    meta["git_rev"] = _git_rev(domain_dir)
    return meta


def _git_rev(start: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=start,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


__all__ = ["collect_run_metadata", "ossie_models_hash"]
