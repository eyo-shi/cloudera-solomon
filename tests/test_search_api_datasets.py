"""Search API — solomon-datasets scope (no live OpenSearch)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from solomon.api.routes.search import list_documents
from solomon.opensearch.scope import search_tab_scope
from solomon.transport.user_context import UserContext


def test_search_tab_scope_is_datasets() -> None:
    assert search_tab_scope() == "datasets"


def test_list_documents_datasets_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = UserContext(user_name="u", groups=[], knox_jwt=None)
    fake_config = MagicMock()
    fake_config.index_name = "solomon-datasets"
    fake_config.namespace = "solomon"

    monkeypatch.setattr(
        "solomon.api.routes.search.get_opensearch_config",
        lambda: fake_config,
    )
    with (
        patch("solomon.api.routes.search.ping", return_value=True),
        patch(
            "solomon.api.routes.search._list_dataset_documents",
            return_value=[
                {
                    "document_type": "dataset",
                    "index": "solomon-datasets",
                    "fq_name": "iceberg.demo.sales",
                    "title": "iceberg.demo.sales",
                }
            ],
        ),
    ):
        out = list_documents(user_ctx=ctx, q="sales", limit=20)

    assert out["scope"] == "datasets"
    assert out["index"] == "solomon-datasets"
    assert out["documents"][0]["document_type"] == "dataset"
