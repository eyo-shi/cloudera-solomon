"""solomon.opensearch.embeddings: query / passage の model 切替と dimensions。"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from solomon.opensearch import embeddings as emb

_BASE = "nvidia/llama-3.2-nv-embedqa-1b-v2"


class _FakeLiteLLM(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("litellm")
        self.calls: list[dict[str, Any]] = []

    def embedding(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"data": [{"embedding": [0.5, 1]} for _ in kwargs["input"]]}


@pytest.fixture
def fake_litellm(monkeypatch: pytest.MonkeyPatch) -> _FakeLiteLLM:
    fake = _FakeLiteLLM()
    monkeypatch.setitem(sys.modules, "litellm", fake)
    return fake


@pytest.fixture
def cai_embedding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SOLOMON_LLM_EMBEDDING_PROVIDER",
        "SOLOMON_LLM_EMBEDDING_API_KEY",
        "SOLOMON_LLM_EMBEDDING_DIMENSIONS",
        "SOLOMON_LLM_EMBEDDING_QUERY_MODEL",
        "SOLOMON_LLM_EMBEDDING_PASSAGE_MODEL",
        "CAI_INFERENCE_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SOLOMON_LLM_PROVIDER", "cai")
    monkeypatch.setenv("CAI_INFERENCE_API_KEY", "cai-key")
    monkeypatch.setenv("SOLOMON_LLM_EMBEDDING_BASE_URL", "https://cai/ep/embedqa/v1")
    monkeypatch.setenv("SOLOMON_LLM_EMBEDDING_MODEL", _BASE)
    monkeypatch.setenv("SOLOMON_LLM_EMBEDDING_QUERY_MODEL", f"{_BASE}-query")
    monkeypatch.setenv("SOLOMON_LLM_EMBEDDING_PASSAGE_MODEL", f"{_BASE}-passage")


def test_query_uses_query_model(fake_litellm: _FakeLiteLLM, cai_embedding_env: None) -> None:
    assert emb.try_embed("質問") == [0.5, 1.0]
    call = fake_litellm.calls[-1]
    assert call["model"] == f"openai/{_BASE}-query"
    assert call["api_base"] == "https://cai/ep/embedqa/v1"
    assert call["api_key"] == "cai-key"
    assert "extra_body" not in call and "dimensions" not in call


def test_passage_uses_passage_model(
    fake_litellm: _FakeLiteLLM, cai_embedding_env: None
) -> None:
    assert emb.try_embed("文書", purpose="passage") == [0.5, 1.0]
    assert fake_litellm.calls[-1]["model"] == f"openai/{_BASE}-passage"


def test_batch_defaults_to_passage(
    fake_litellm: _FakeLiteLLM, cai_embedding_env: None
) -> None:
    out = emb.try_embed_batch(["a", "b"])
    assert out == [[0.5, 1.0], [0.5, 1.0]]
    assert fake_litellm.calls[-1]["model"] == f"openai/{_BASE}-passage"


def test_falls_back_to_base_model(
    fake_litellm: _FakeLiteLLM,
    cai_embedding_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SOLOMON_LLM_EMBEDDING_QUERY_MODEL")
    emb.try_embed("質問")
    assert fake_litellm.calls[-1]["model"] == f"openai/{_BASE}"


def test_explicit_model_wins(fake_litellm: _FakeLiteLLM, cai_embedding_env: None) -> None:
    emb.try_embed("質問", model="bge-m3")
    assert fake_litellm.calls[-1]["model"] == "openai/bge-m3"


def test_dimensions_sent_via_extra_body_for_openai_compatible(
    fake_litellm: _FakeLiteLLM,
    cai_embedding_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LiteLLM は openai/ の非 text-embedding-3 モデルで dimensions を拒否するため body に載せる。"""
    monkeypatch.setenv("SOLOMON_LLM_EMBEDDING_DIMENSIONS", "1024")
    emb.try_embed_batch(["a"])
    call = fake_litellm.calls[-1]
    assert call["extra_body"] == {"dimensions": 1024}
    assert "dimensions" not in call


def test_dimensions_kwarg_for_bedrock(
    fake_litellm: _FakeLiteLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOLOMON_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("SOLOMON_LLM_EMBEDDING_DIMENSIONS", "512")
    for key in (
        "SOLOMON_LLM_EMBEDDING_PROVIDER",
        "SOLOMON_LLM_EMBEDDING_MODEL",
        "SOLOMON_LLM_EMBEDDING_QUERY_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    emb.try_embed("q")
    call = fake_litellm.calls[-1]
    assert call["model"] == "bedrock/amazon.titan-embed-text-v2:0"
    assert call["dimensions"] == 512
    assert call["aws_region_name"] == "us-east-1"


def test_failure_returns_none(
    cai_embedding_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = types.ModuleType("litellm")

    def boom(**_kw: Any) -> None:
        raise RuntimeError("401")

    fake.embedding = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake)
    assert emb.try_embed("q") is None
    assert emb.try_embed_batch(["a", "b"]) == [None, None]
