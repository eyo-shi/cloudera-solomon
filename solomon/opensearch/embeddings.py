"""Embedding generation for vector search against external OpenSearch."""

from __future__ import annotations

import os
from typing import Optional

from solomon.transport.config import get_llm_role_config
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

    cfg = get_llm_role_config("embedding")
    if cfg is None:
        _logger.debug("opensearch.embeddings.llm_not_configured")
        return None

    resolved = model or cfg.model
    prefixed = _apply_prefix(cfg.provider, resolved)

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


def try_embed_batch(texts: list[str], *, model: Optional[str] = None) -> list[list[float] | None]:
    """複数テキストを 1 回の embedding API 呼び出しでベクトル化。"""
    if not texts:
        return []
    try:
        import litellm  # type: ignore
    except ImportError:
        _logger.debug("opensearch.embeddings.litellm_not_installed")
        return [None] * len(texts)

    cfg = get_llm_role_config("embedding")
    if cfg is None:
        return [None] * len(texts)

    inputs = [t[:8000] if t else " " for t in texts]
    resolved = model or cfg.model
    prefixed = _apply_prefix(cfg.provider, resolved)
    kwargs: dict = {"model": prefixed, "input": inputs}
    if cfg.api_base:
        kwargs["api_base"] = cfg.api_base
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key

    try:
        response = litellm.embedding(**kwargs)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("opensearch.embeddings.batch_failed", error=str(exc))
        return [None] * len(texts)

    data = getattr(response, "data", None) or response.get("data", [])
    out: list[list[float] | None] = [None] * len(texts)
    for i, item in enumerate(data):
        if i >= len(out):
            break
        embedding = getattr(item, "embedding", None) or item.get("embedding")
        if isinstance(embedding, list):
            out[i] = [float(v) for v in embedding]
    return out


__all__ = ["try_embed", "try_embed_batch"]
