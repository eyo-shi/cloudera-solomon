"""OpenSearch deploy/startup index bootstrap."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from solomon.opensearch import bootstrap as bootstrap_mod
from solomon.transport.config import OpenSearchConfig


def test_bootstrap_skipped_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap_mod, "get_opensearch_config", lambda: None)
    assert bootstrap_mod.bootstrap_search_index() is False


def test_bootstrap_skipped_when_ping_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    config = OpenSearchConfig(host="localhost", port=9200, scheme="http", verify_ssl=False)
    monkeypatch.setattr(bootstrap_mod, "get_opensearch_config", lambda: config)
    monkeypatch.setattr(bootstrap_mod, "ping", lambda _cfg: False)
    assert bootstrap_mod.bootstrap_search_index() is False


def test_bootstrap_creates_index(monkeypatch: pytest.MonkeyPatch) -> None:
    config = OpenSearchConfig(
        host="localhost",
        port=9200,
        scheme="http",
        verify_ssl=False,
        index_name="solomon-datasets",
    )
    client = MagicMock()
    client.indices.exists.return_value = False
    ensure_index = MagicMock()

    monkeypatch.setattr(bootstrap_mod, "get_opensearch_config", lambda: config)
    monkeypatch.setattr(bootstrap_mod, "ping", lambda _cfg: True)
    monkeypatch.setattr(bootstrap_mod, "build_client", lambda _cfg: client)
    monkeypatch.setattr(bootstrap_mod, "ensure_index", ensure_index)

    assert bootstrap_mod.bootstrap_search_index() is True
    ensure_index.assert_called_once_with(client, config)


def _config() -> OpenSearchConfig:
    return OpenSearchConfig(
        host="localhost",
        port=9200,
        scheme="http",
        verify_ssl=False,
        index_name="solomon-datasets",
    )


def test_ensure_index_uses_lucene_not_nmslib() -> None:
    from solomon.opensearch.indexer import ensure_index

    client = MagicMock()
    client.indices.exists.return_value = False
    ensure_index(client, _config())
    body = client.indices.create.call_args.kwargs["body"]
    assert body["mappings"]["properties"]["embedding"]["method"]["engine"] == "lucene"


def test_ensure_index_falls_back_to_faiss() -> None:
    from solomon.opensearch.indexer import ensure_index

    client = MagicMock()
    client.indices.exists.return_value = False
    client.indices.create.side_effect = [RuntimeError("lucene rejected"), None]
    ensure_index(client, _config())
    engines = [
        c.kwargs["body"]["mappings"]["properties"]["embedding"]["method"]["engine"]
        for c in client.indices.create.call_args_list
    ]
    assert engines == ["lucene", "faiss"]


def test_ensure_index_raises_when_all_engines_fail() -> None:
    from solomon.opensearch.indexer import ensure_index

    client = MagicMock()
    client.indices.exists.return_value = False
    client.indices.create.side_effect = RuntimeError("denied")
    with pytest.raises(RuntimeError, match="denied"):
        ensure_index(client, _config())


def test_ping_treats_cluster_monitor_403_as_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opensearchpy.exceptions import AuthorizationException

    from solomon.opensearch import client as client_mod

    fake = MagicMock()
    fake.cluster.health.side_effect = AuthorizationException(
        403, "security_exception", "no permissions for [cluster:monitor/health]"
    )
    monkeypatch.setattr(client_mod, "build_client", lambda _cfg: fake)
    assert client_mod.ping(_config()) is True


def test_ping_false_on_authentication_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from opensearchpy.exceptions import AuthenticationException

    from solomon.opensearch import client as client_mod

    fake = MagicMock()
    fake.cluster.health.side_effect = AuthenticationException(401, "unauthorized", "")
    monkeypatch.setattr(client_mod, "build_client", lambda _cfg: fake)
    assert client_mod.ping(_config()) is False


def test_bulk_index_sends_ndjson_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """CDP Semantic Search gateway は application/json の _bulk 末尾改行を落とす。"""
    import opensearchpy.helpers as helpers

    from solomon.opensearch import docs_indexer

    fake = MagicMock()
    monkeypatch.setattr(docs_indexer, "build_client", lambda _cfg: fake)
    seen: dict[str, Any] = {}

    def _bulk(client: Any, actions: Any, **kwargs: Any) -> tuple[int, list[Any]]:
        seen.update(kwargs)
        return len(list(actions)), []

    monkeypatch.setattr(helpers, "bulk", _bulk)
    cfg = OpenSearchConfig(
        host="localhost", port=9200, scheme="http", verify_ssl=False,
        docs_index_name="solomon-docs",
    )
    out = docs_indexer.bulk_index_doc_chunks(
        cfg, [{"chunk_id": "c1", "text": "t"}], with_embedding=False, ensure_index=False
    )
    assert out["indexed"] == 1
    assert seen["headers"] == {"Content-Type": "application/x-ndjson"}


def _bulk_capture(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, dict[str, Any]]:
    import opensearchpy.helpers as helpers

    from solomon.opensearch import docs_indexer

    monkeypatch.setattr(docs_indexer, "build_client", lambda _cfg: MagicMock())
    seen: dict[str, Any] = {"actions": []}

    def _bulk(client: Any, actions: Any, **kwargs: Any) -> tuple[int, list[Any]]:
        acts = list(actions)
        seen["actions"].extend(acts)
        seen.update(kwargs)
        return len(acts), []

    monkeypatch.setattr(helpers, "bulk", _bulk)
    return docs_indexer, seen


def _docs_cfg() -> OpenSearchConfig:
    return OpenSearchConfig(
        host="localhost", port=9200, scheme="http", verify_ssl=False,
        docs_index_name="solomon-docs",
    )


def test_bulk_index_caps_request_size_for_knox(monkeypatch: pytest.MonkeyPatch) -> None:
    """Knox は約 16 KiB を超える本文を再送できず 500 になる。"""
    monkeypatch.delenv("OPENSEARCH_BULK_MAX_BYTES", raising=False)
    docs_indexer, seen = _bulk_capture(monkeypatch)
    docs_indexer.bulk_index_doc_chunks(
        _docs_cfg(), [{"chunk_id": "c1", "text": "t"}], with_embedding=False, ensure_index=False
    )
    assert seen["max_chunk_bytes"] == 12 * 1024


def test_bulk_max_bytes_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSEARCH_BULK_MAX_BYTES", "1048576")
    docs_indexer, seen = _bulk_capture(monkeypatch)
    docs_indexer.bulk_index_doc_chunks(
        _docs_cfg(), [{"chunk_id": "c1", "text": "t"}], with_embedding=False, ensure_index=False
    )
    assert seen["max_chunk_bytes"] == 1048576


def test_bulk_index_skips_chunk_larger_than_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENSEARCH_BULK_MAX_BYTES", raising=False)
    docs_indexer, seen = _bulk_capture(monkeypatch)
    out = docs_indexer.bulk_index_doc_chunks(
        _docs_cfg(),
        [{"chunk_id": "small", "text": "t"}, {"chunk_id": "big", "text": "あ" * 8000}],
        with_embedding=False,
        ensure_index=False,
    )
    assert [a["_id"] for a in seen["actions"]] == ["small"]
    assert out["indexed"] == 1
    assert any("big" in e for e in out["errors"])


def test_1024_dim_embedding_chunk_fits_bulk_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """丸めた 1024 次元ベクトル + 本文 1 件が上限に収まる。"""
    import random

    from solomon.opensearch import embeddings

    rng = random.Random(0)
    raw = [rng.uniform(-0.1, 0.1) for _ in range(1024)]
    vec = embeddings._vector({"embedding": raw})
    assert vec is not None
    assert all(abs(a - b) < 1e-6 for a, b in zip(vec, raw, strict=True))

    monkeypatch.delenv("OPENSEARCH_BULK_MAX_BYTES", raising=False)
    docs_indexer, seen = _bulk_capture(monkeypatch)
    monkeypatch.setattr(docs_indexer, "try_embed_batch", lambda texts, purpose: [vec] * len(texts))
    out = docs_indexer.bulk_index_doc_chunks(
        _docs_cfg(),
        [{"chunk_id": "c1", "doc_id": "d1", "title": "作業日報", "text": "異音を確認。" * 50}],
        ensure_index=False,
    )
    assert out["indexed"] == 1, out["errors"]
