"""Search API — inspection-* scope (no live OpenSearch)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from solomon.opensearch.inspection_indices import (
    normalize_inspection_hit,
    search_tab_scope,
    _inspection_search_body,
)
from solomon.transport import config as cfg_mod


def test_search_tab_scope_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENSEARCH_SEARCH_SCOPE", raising=False)
    assert search_tab_scope() == "inspection"


def test_search_tab_scope_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSEARCH_SEARCH_SCOPE", "datasets")
    assert search_tab_scope() == "datasets"


def test_inspection_search_body_match_all() -> None:
    body = _inspection_search_body("", size=10)
    assert body["query"] == {"match_all": {}}
    assert body["size"] == 10


def test_inspection_search_body_keyword() -> None:
    body = _inspection_search_body("26G3V05307", size=5)
    assert "multi_match" in str(body["query"])
    assert body["size"] == 5


def test_normalize_inspection_hit() -> None:
    doc = normalize_inspection_hit(
        {
            "_index": "inspection-j5_shukken_id",
            "_score": 1.5,
            "_source": {
                "object_key": "j5_shukken_id/FOO.DAT",
                "format": "j5_shukken_id",
                "trace_id": "26G3V05307",
                "vb_machine_no": "",
                "payload": {"customer_hinban": "3061042090"},
            },
        }
    )
    assert doc["document_type"] == "inspection"
    assert doc["title"] == "FOO.DAT"
    assert doc["trace_id"] == "26G3V05307"
    assert "customer_hinban" in (doc["subtitle"] or "")


def test_list_documents_inspection_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSEARCH_MODE", "external")
    monkeypatch.setenv("OPENSEARCH_ENDPOINT", "https://css.example.com:9200")
    config = cfg_mod.get_opensearch_config()
    assert config is not None

    fake_docs = [
        {
            "document_type": "inspection",
            "title": "a.DAT",
            "object_key": "j5/a.DAT",
            "score": 1.0,
        }
    ]

    with (
        patch("solomon.api.routes.search.get_opensearch_config", return_value=config),
        patch("solomon.api.routes.search.ping", return_value=True),
        patch(
            "solomon.api.routes.search.search_inspection_documents",
            return_value=fake_docs,
        ) as search_mock,
    ):
        from solomon.api.routes.search import list_documents

        ctx = SimpleNamespace(user_id="u", tenant_id="t")
        out = list_documents(user_ctx=ctx, q="26G3", limit=20, scope="inspection")

    search_mock.assert_called_once_with(config, "26G3", limit=20)
    assert out["scope"] == "inspection"
    assert out["documents"] == fake_docs
    assert out["index"] == "inspection-*"
