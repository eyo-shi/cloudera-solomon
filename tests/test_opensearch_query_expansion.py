"""doc_search LLM query expansion (mock LLM, neutral Ossie fixture)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from solomon.opensearch.docs_search import (
    merge_expanded_document_results,
    search_documents_with_expansion,
)
from solomon.opensearch.query_expansion import (
    build_expansion_prompt,
    clear_expansion_cache,
    doc_search_expansion_enabled,
    expand_query,
)
from solomon.semantic.context import get_semantic_context
from solomon.transport.config import OpenSearchConfig

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "semantic" / "sample_orders"


@pytest.fixture(autouse=True)
def _semantic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_SEMANTIC_ROOT", str(FIXTURE_ROOT))
    from solomon.semantic import store as store_mod

    store_mod.load_models(force=True)
    from solomon.semantic import context as ctx_mod

    ctx_mod._cache_ctx = None
    clear_expansion_cache()


def _test_config() -> OpenSearchConfig:
    return OpenSearchConfig(
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


def _doc(chunk_id: str, *, score: float = 1.0) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "doc_id": "d1",
        "title": "t",
        "snippet": "s",
        "text": chunk_id,
        "score": score,
        "metadata": {},
    }


def test_merge_expanded_document_results_weighted_rrf() -> None:
    ranked = [
        ("original q", 1.0, [_doc("c_orig", score=1.0)]),
        ("variant a", 0.7, [_doc("c_var", score=1.0)]),
    ]
    merged = merge_expanded_document_results(ranked, top_k=5)
    assert merged[0]["chunk_id"] == "c_orig"
    assert merged[0]["matched_queries"] == ["original q"]
    assert any(m["chunk_id"] == "c_var" for m in merged)
    var_row = next(m for m in merged if m["chunk_id"] == "c_var")
    assert "variant a" in var_row["matched_queries"]


def test_search_with_expansion_off_single_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_search(_cfg: OpenSearchConfig, query: str, **_k: Any) -> dict[str, Any]:
        calls.append(query)
        return {
            "status": "ok",
            "documents": [_doc("c1")],
            "warnings": [],
            "index": "support_notes",
        }

    monkeypatch.setattr(
        "solomon.opensearch.docs_search.search_documents",
        fake_search,
    )
    monkeypatch.setattr(
        "solomon.opensearch.query_expansion.expand_query",
        lambda *_a, **_k: ["should not run"],
    )

    result = search_documents_with_expansion(
        _test_config(),
        "hello",
        expand=False,
    )
    assert result["status"] == "ok"
    assert calls == ["hello"]
    assert result["expanded_queries"] == []
    assert result["documents"][0]["matched_queries"] == ["hello"]


def test_search_with_expansion_merges_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "solomon.opensearch.query_expansion.expand_query",
        lambda _q, **_k: ["variant one"],
    )

    def fake_search(_cfg: OpenSearchConfig, query: str, **_k: Any) -> dict[str, Any]:
        if query == "hello":
            return {"status": "ok", "documents": [_doc("c_kw")], "warnings": []}
        return {"status": "ok", "documents": [_doc("c_var")], "warnings": []}

    monkeypatch.setattr(
        "solomon.opensearch.docs_search.search_documents",
        fake_search,
    )

    result = search_documents_with_expansion(
        _test_config(),
        "hello",
        expand=True,
        max_variants=2,
    )
    assert result["expanded_queries"] == ["variant one"]
    ids = [d["chunk_id"] for d in result["documents"]]
    assert "c_kw" in ids and "c_var" in ids


def test_expand_query_llm_failure_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "solomon.opensearch.query_expansion.try_json_completion",
        lambda *_a, **_k: None,
    )
    assert expand_query("test query") == []


def test_expand_query_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_llm = mock.Mock(return_value={"variants": ["alt phrasing"]})
    monkeypatch.setattr(
        "solomon.opensearch.query_expansion.try_json_completion",
        mock_llm,
    )
    assert expand_query("cached q") == ["alt phrasing"]
    assert expand_query("cached q") == ["alt phrasing"]
    assert mock_llm.call_count == 1


def test_build_expansion_prompt_includes_ossie_hints() -> None:
    ctx = get_semantic_context()
    prompt = build_expansion_prompt("order_line status", context=ctx, max_variants=3)
    assert "Writers mix casual phrasing" in prompt
    assert "line item" in prompt or "detail row" in prompt


def test_build_expansion_prompt_respects_use_synonyms_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = get_semantic_context()

    def fake_settings(_ctx: Any) -> dict[str, Any]:
        return {
            "expansion_instructions": "Neutral writer note.",
            "use_synonyms": False,
        }

    monkeypatch.setattr(
        "solomon.opensearch.query_expansion._search_settings_from_context",
        fake_settings,
    )
    prompt = build_expansion_prompt("order_line", context=ctx)
    assert "Neutral writer note." in prompt
    assert "参考になる既知の別名" not in prompt


def test_doc_search_expansion_env_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOLOMON_DOC_SEARCH_EXPANSION", "off")
    assert doc_search_expansion_enabled() is False
