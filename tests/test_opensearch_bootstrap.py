"""OpenSearch deploy/startup index bootstrap."""

from __future__ import annotations

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
