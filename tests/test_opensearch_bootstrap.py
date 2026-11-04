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
