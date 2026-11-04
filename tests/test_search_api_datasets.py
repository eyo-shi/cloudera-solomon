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


def _patch_config(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    fake_config = MagicMock()
    fake_config.index_name = "solomon-datasets"
    fake_config.docs_index_name = "solomon-docs"
    fake_config.namespace = "solomon"
    monkeypatch.setattr(
        "solomon.api.routes.search.get_opensearch_config", lambda: fake_config
    )
    return fake_config


_DATASET = {"document_type": "dataset", "index": "solomon-datasets", "fq_name": "a.b.c"}
_DOC_HIT = {"chunk_id": "c1", "doc_id": "d1", "title": "作業日報", "score": 0.5}


def test_both_scope_returns_flat_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Search タブは documents を配列として描画する (dict だと画面が落ちる)。"""
    _patch_config(monkeypatch)
    ctx = UserContext(user_name="u", groups=[], knox_jwt=None)
    with (
        patch("solomon.api.routes.search.ping", return_value=True),
        patch("solomon.api.routes.search._list_dataset_documents", return_value=[_DATASET]),
        patch(
            "solomon.api.routes.search.search_documents",
            return_value={"status": "ok", "documents": [_DOC_HIT]},
        ) as search_docs,
    ):
        out = list_documents(user_ctx=ctx, q="異音", limit=20, scope="both")

    assert isinstance(out["documents"], list)
    assert [d["document_type"] for d in out["documents"]] == ["dataset", "doc"]
    assert out["documents"][1]["index"] == "solomon-docs"
    assert search_docs.call_args.kwargs["group_by_doc"] is True


def test_both_scope_without_docs_index_returns_datasets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_config(monkeypatch)
    ctx = UserContext(user_name="u", groups=[], knox_jwt=None)
    with (
        patch("solomon.api.routes.search.ping", return_value=True),
        patch("solomon.api.routes.search._list_dataset_documents", return_value=[_DATASET]),
        patch(
            "solomon.api.routes.search.search_documents",
            return_value={"status": "error", "error_code": "OPENSEARCH_DOCS_INDEX_MISSING"},
        ),
    ):
        out = list_documents(user_ctx=ctx, q="x", limit=20, scope="both")
    assert out["documents"] == [_DATASET]


def test_docs_scope_empty_query_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_config(monkeypatch)
    ctx = UserContext(user_name="u", groups=[], knox_jwt=None)
    with (
        patch("solomon.api.routes.search.ping", return_value=True),
        patch("solomon.api.routes.search.search_documents") as search_docs,
    ):
        out = list_documents(user_ctx=ctx, q="", limit=20, scope="docs")
    assert out["documents"] == []
    assert out["scope"] == "docs"
    search_docs.assert_not_called()
