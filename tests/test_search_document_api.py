"""``GET /api/search/document`` doc_id 経路と graph artifact ヘルパ。"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from solomon.api.routes.wish import _last_successful_graph_cypher

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "semantic" / "sample_orders"


@pytest.fixture(autouse=True)
def _semantic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_SEMANTIC_ROOT", str(FIXTURE_ROOT))
    from solomon.semantic import store as store_mod

    store_mod.load_models(force=True)
    from solomon.semantic import context as ctx_mod

    ctx_mod._cache_ctx = None


def test_get_document_by_doc_id(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "solomon.api.routes.search.get_opensearch_config",
        lambda: mock.Mock(
            docs_index_name="support_notes",
            namespace="solomon",
            index_name="idx",
        ),
    )
    monkeypatch.setattr("solomon.api.routes.search.ping", lambda _c: True)
    monkeypatch.setattr(
        "solomon.opensearch.document_payload.get_document_chunks",
        lambda _cfg, doc_id: [
            {
                "chunk_id": "c1",
                "section": "intro",
                "text": "hello",
                "title": "T1",
                "doc_type": "inquiry",
                "doc_type_label": "Inquiry",
                "doc_date": "2024-03-01",
                "metadata": {"note_type": "inquiry"},
            }
        ],
    )

    r = client.get(
        "/api/search/document",
        params={"doc_id": "doc-99"},
        headers={"Authorization": "Bearer fake.jwt.token"},
    )
    assert r.status_code == 200
    doc = r.json()["document"]
    assert doc["document_type"] == "doc"
    assert doc["doc_id"] == "doc-99"
    assert "note_type" in doc["metadata_labels"]
    assert doc["chunks"][0]["chunk_id"] == "c1"


def test_last_successful_graph_cypher_from_tool_calls() -> None:
    calls = [
        {"name": "graph_query", "ok": False, "args": {"cypher": "BAD"}},
        {
            "name": "graph_query",
            "ok": True,
            "args": {
                "cypher": "MATCH (n) RETURN n LIMIT 1",
                "params": {"id": "x"},
            },
        },
    ]
    out = _last_successful_graph_cypher(calls)
    assert out is not None
    assert "MATCH" in out["cypher"]
    assert out["params"] == {"id": "x"}
