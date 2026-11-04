"""Embedding generation for vector search against external OpenSearch.

``purpose`` で検索 (``query``) と索引 (``passage``) を区別する。非対称 embedding
モデル (NVIDIA embedqa 等) は用途ごとに model ID が異なるため
(:func:`~solomon.transport.config.embedding_model_for_purpose`)、索引側と検索側で
取り違えると検索精度が落ちる。
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from solomon.transport.config import (
    embedding_model_for_purpose,
    get_embedding_dimensions,
    get_llm_role_config,
)
from solomon.transport.llm_factory import _apply_prefix
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

EmbeddingPurpose = Literal["query", "passage"]


def _embedding_kwargs(
    inputs: list[str],
    *,
    model: Optional[str],
    purpose: EmbeddingPurpose,
) -> Optional[dict[str, Any]]:
    """``litellm.embedding`` の kwargs。LLM 未設定なら ``None``。"""
    cfg = get_llm_role_config("embedding")
    if cfg is None:
        _logger.debug("opensearch.embeddings.llm_not_configured")
        return None

    resolved = model or embedding_model_for_purpose(cfg.model, purpose)
    kwargs: dict[str, Any] = {
        "model": _apply_prefix(cfg.provider, resolved),
        "input": inputs,
    }
    if cfg.api_base:
        kwargs["api_base"] = cfg.api_base
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key
    if cfg.provider == "bedrock" and cfg.aws_region:
        kwargs["aws_region_name"] = cfg.aws_region

    dimensions = get_embedding_dimensions()
    if dimensions is not None:
        if cfg.provider in ("cai", "openai"):
            # LiteLLM は text-embedding-3 以外の openai/ モデルで dimensions を
            # UnsupportedParamsError にするため、リクエスト body に直接載せる。
            kwargs["extra_body"] = {"dimensions": dimensions}
        else:
            kwargs["dimensions"] = dimensions
    return kwargs


#: ベクトル成分の小数桁数。CDP Semantic Search の Knox は再送用に本文を約 16 KiB
#: までしか保持できず、超えると 500 (NonRepeatableRequestException) になる。
#: 丸めないと 1024 次元で JSON が約 20 KB、6 桁なら約 10 KB に収まる
#: (knn_vector は float32 なので実質的な精度は落ちない)
EMBEDDING_DECIMALS = 6


def _vector(item: Any) -> list[float] | None:
    embedding = getattr(item, "embedding", None)
    if embedding is None and isinstance(item, dict):
        embedding = item.get("embedding")
    if not isinstance(embedding, list):
        return None
    return [round(float(v), EMBEDDING_DECIMALS) for v in embedding]


def _response_data(response: Any) -> list[Any]:
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")
    return list(data or [])


def try_embed(
    text: str,
    *,
    model: Optional[str] = None,
    purpose: EmbeddingPurpose = "query",
) -> list[float] | None:
    """1 テキストをベクトル化する。既定は検索クエリ用 (``purpose="query"``)。"""
    if not text.strip():
        return None

    try:
        import litellm  # type: ignore
    except ImportError:
        _logger.debug("opensearch.embeddings.litellm_not_installed")
        return None

    kwargs = _embedding_kwargs([text], model=model, purpose=purpose)
    if kwargs is None:
        return None

    try:
        response = litellm.embedding(**kwargs)
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "opensearch.embeddings.failed",
            purpose=purpose,
            model=kwargs["model"],
            error=str(exc),
        )
        return None

    data = _response_data(response)
    if not data:
        return None
    return _vector(data[0])


def try_embed_batch(
    texts: list[str],
    *,
    model: Optional[str] = None,
    purpose: EmbeddingPurpose = "passage",
) -> list[list[float] | None]:
    """複数テキストを 1 回の API 呼び出しでベクトル化。既定は索引用 (``passage``)。"""
    if not texts:
        return []
    try:
        import litellm  # type: ignore
    except ImportError:
        _logger.debug("opensearch.embeddings.litellm_not_installed")
        return [None] * len(texts)

    inputs = [t[:8000] if t else " " for t in texts]
    kwargs = _embedding_kwargs(inputs, model=model, purpose=purpose)
    if kwargs is None:
        return [None] * len(texts)

    try:
        response = litellm.embedding(**kwargs)
    except Exception as exc:  # noqa: BLE001
        _logger.warning(
            "opensearch.embeddings.batch_failed",
            purpose=purpose,
            model=kwargs["model"],
            error=str(exc),
        )
        return [None] * len(texts)

    out: list[list[float] | None] = [None] * len(texts)
    for i, item in enumerate(_response_data(response)[: len(out)]):
        out[i] = _vector(item)
    return out


__all__ = ["EMBEDDING_DECIMALS", "EmbeddingPurpose", "try_embed", "try_embed_batch"]
