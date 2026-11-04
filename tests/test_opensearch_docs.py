"""Business document OpenSearch (mock client, neutral Ossie fixture)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from solomon.opensearch.doc_index import build_doc_search_tool_description
from solomon.opensearch.docs_mapping import build_docs_mapping
from solomon.opensearch.docs_search import _parse_filters, search_documents
from solomon.transport.config import OpenSearchConfig

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "semantic" / "sample_orders"


@pytest.fixture(autouse=True)
def _semantic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_SEMANTIC_ROOT", str(FIXTURE_ROOT))
    from solomon.semantic import store as store_mod

    store_mod.load_models(force=True)
    from solomon.semantic import context as ctx_mod

    ctx_mod._cache_ctx = None


def _test_config(**overrides: Any) -> OpenSearchConfig:
    base = OpenSearchConfig(
        host="localhost",
        port=9200,
        scheme="http",
        verify_ssl=False,
        namespace="solomon",
        index_name="solomon-datasets",
        docs_index_name="support_notes",
        docs_analyzer="cjk",
        embedding_dim=8,
    )
    return base if not overrides else OpenSearchConfig(**{**base.__dict__, **overrides})


def test_build_docs_mapping_cjk_and_filterable() -> None:
    body = build_docs_mapping({}, analyzer="cjk", embedding_dim=8, knn_engine="lucene")
    props = body["mappings"]["properties"]
    assert props["text"]["analyzer"] == "docs_text_analyzer"
    assert body["settings"]["analysis"]["analyzer"]["docs_text_analyzer"]["type"] == "cjk"
    assert "note_type" in props
    assert props["embedding"]["method"]["engine"] == "lucene"


def test_build_docs_mapping_kuromoji() -> None:
    body = build_docs_mapping({}, analyzer="kuromoji", embedding_dim=8)
    analyzers = body["settings"]["analysis"]["analyzer"]
    assert analyzers["docs_text_analyzer"]["tokenizer"] == "docs_kuromoji"


def test_parse_filters_warns_unknown_key() -> None:
    clauses, warnings, norm = _parse_filters(
        {"doc_type": ["inquiry"], "bogus_field": "x", "date_from": "2024-01-01"}
    )
    assert any("bogus_field" in w for w in warnings)
    assert norm["doc_type"] == ["inquiry"]
    assert any("range" in str(c) for c in clauses)


def test_search_documents_rrf_uses_chunk_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _test_config()
    captured: dict[str, Any] = {}

    class FakeIndices:
        def exists(self, *, index: str) -> bool:
            return True

    class FakeClient:
        indices = FakeIndices()

        def search(self, *, index: str, body: dict) -> dict:
            captured.setdefault("calls", []).append(body)
            if "knn" in str(body.get("query", {})):
                return {
                    "hits": {
                        "hits": [
                            {
                                "_score": 0.9,
                                "_source": {
                                    "chunk_id": "c2",
                                    "doc_id": "d1",
                                    "text": "vector hit",
                                    "title": "t",
                                },
                            }
                        ]
                    }
                }
            return {
                "hits": {
                    "hits": [
                        {
                            "_score": 1.0,
                            "_source": {
                                "chunk_id": "c1",
                                "doc_id": "d1",
                                "text": "keyword hit",
                                "title": "t",
                            },
                        },
                        {
                            "_score": 0.5,
                            "_source": {
                                "chunk_id": "c2",
                                "doc_id": "d1",
                                "text": "keyword hit 2",
                                "title": "t",
                            },
                        },
                    ]
                }
            }

    monkeypatch.setattr(
        "solomon.opensearch.docs_search.build_client",
        lambda _cfg: FakeClient(),
    )
    monkeypatch.setattr(
        "solomon.opensearch.docs_search.try_embed",
        lambda _q, **_kw: [0.1] * 8,
    )

    result = search_documents(config, "test query", top_k=2, mode="hybrid")
    assert result["status"] == "ok"
    docs = result["documents"]
    assert len(docs) == 2
    chunk_ids = {d["chunk_id"] for d in docs}
    assert "c1" in chunk_ids and "c2" in chunk_ids


def test_search_documents_vector_error_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _test_config()

    class FakeIndices:
        def exists(self, *, index: str) -> bool:
            return True

    class FakeClient:
        indices = FakeIndices()

        call_n = {"n": 0}

        def search(self, *, index: str, body: dict) -> dict:
            if "knn" in str(body.get("query", {})):
                call_n["n"] += 1
                if call_n["n"] == 1:
                    raise RuntimeError("knn filter unsupported")
            return {"hits": {"hits": []}}

    monkeypatch.setattr(
        "solomon.opensearch.docs_search.build_client",
        lambda _cfg: FakeClient(),
    )
    monkeypatch.setattr(
        "solomon.opensearch.docs_search.try_embed",
        lambda _q, **_kw: [0.0] * 8,
    )

    result = search_documents(config, "q", mode="hybrid", top_k=3)
    assert result["status"] == "ok"
    if result["documents"]:
        assert result["documents"][0].get("vector_error")


def test_doc_search_tool_description_from_ossie() -> None:
    desc = build_doc_search_tool_description()
    assert "inquiry" in desc.lower() or "Inquiry" in desc
    assert "note_type" in desc


def test_document_search_tool_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from solomon.tools.opensearch import DocumentSearchTool

    monkeypatch.setattr(
        "solomon.tools.opensearch.get_opensearch_config",
        lambda: _test_config(),
    )
    monkeypatch.setattr(
        "solomon.tools.opensearch.search_documents_with_expansion",
        lambda *_a, **_k: {
            "status": "ok",
            "documents": [
                {
                    "doc_id": "d1",
                    "chunk_id": "c1",
                    "title": "T",
                    "snippet": "s",
                    "text": "body",
                    "score": 1.0,
                    "metadata": {"note_type": "inquiry"},
                }
            ],
            "count": 1,
            "warnings": [],
            "index": "support_notes",
            "expanded_queries": [],
        },
    )
    out = DocumentSearchTool().run(user_ctx=None, query="q", expand=False)
    assert out["status"] == "ok"
    doc = out["documents"][0]
    assert doc["doc_id"] == "d1"
    assert doc["metadata"]["note_type"] == "inquiry"
