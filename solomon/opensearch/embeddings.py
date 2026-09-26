"""Embedding generation for vector search against external OpenSearch."""

from __future__ import annotations

import os
from typing import Optional

from solomon.transport.config import get_llm_config
from solomon.transport.llm_factory import _apply_prefix
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)


def try_embed(text: str, *, model: Optional[str] = None) -> list[float] | None:
    """LLM embedding API でクエリをベクトル化する (vector search 用)。"""
    if not text.strip():
        return None

    try:
        import litellm  # type: ignore
    except ImportError:
        _logger.debug("opensearch.embeddings.litellm_not_installed")
        return None

    cfg = get_llm_config()
    if cfg is None:
        _logger.debug("opensearch.embeddings.llm_not_configured")
        return None

    resolved = model or os.environ.get("SOLOMON_LLM_EMBEDDING_MODEL", "bge-m3").strip()
    prefixed = _apply_prefix(cfg.provider, resolved or "bge-m3")

    kwargs: dict = {"model": prefixed, "input": [text]}
    if cfg.api_base:
        kwargs["api_base"] = cfg.api_base
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key

    try:
        response = litellm.embedding(**kwargs)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("opensearch.embeddings.failed", error=str(exc))
        return None

    data = getattr(response, "data", None) or response.get("data", [])
    if not data:
        return None
    first = data[0]
    embedding = getattr(first, "embedding", None) or first.get("embedding")
    if not isinstance(embedding, list):
        return None
    return [float(v) for v in embedding]


__all__ = ["try_embed"]
