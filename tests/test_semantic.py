"""Ossie official-format semantic layer tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "semantic" / "sample_orders"
LEGACY_ROOT = Path(__file__).resolve().parent / "fixtures" / "semantic" / "sample_legacy"


@pytest.fixture(autouse=True)
def _semantic_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_SEMANTIC_ROOT", str(FIXTURE_ROOT))
    monkeypatch.delenv("SOLOMON_SEMANTIC_MODELS", raising=False)
    from solomon.semantic import store as store_mod

    store_mod.load_models(force=True)


def test_load_models_and_list_datasets() -> None:
    from solomon.semantic.store import list_datasets, load_models

    models = load_models(force=True)
    assert len(models) == 1
    assert models[0].name == "sample_orders"
    listed = list_datasets()
    fq_names = {x["fq_name"] for x in listed}
    assert "demo_catalog.demo_schema.customers" in fq_names


def test_read_dataset_by_fq() -> None:
    from solomon.semantic.store import read_dataset

    r = read_dataset("demo_catalog.demo_schema.orders")
    assert r["status"] == "ok"
    ds = r["dataset"]
    assert "fields" in ds
    assert any(f["name"] == "order_id" for f in ds["fields"])


def test_search_japanese() -> None:
    from solomon.semantic.store import search_datasets

    hits = search_datasets("顧客 マスタ", top_k=3)
    assert hits
    assert any("customers" in h["fq_name"] for h in hits)


def test_semantic_context_public() -> None:
    from solomon.semantic.context import get_semantic_context

    ctx = get_semantic_context(force=True)
    pub = ctx.to_public_dict()
    assert "sample_orders" in pub["models"]
    assert pub["glossary"]
    assert pub["graph_labels"]


def test_solomon_extension_mapping() -> None:
    from solomon.semantic.solomon_extension import extract_solomon_extensions
    from solomon.semantic.store import load_models

    model = load_models(force=True)[0]
    ext = extract_solomon_extensions(model.custom_extensions)
    assert ext.get("tool_hints", {}).get("table")


def test_legacy_wrapped_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_SEMANTIC_ROOT", str(LEGACY_ROOT))
    from solomon.semantic import store as store_mod

    store_mod.load_models(force=True)
    models = store_mod.load_models(force=True)
    assert models[0].name == "legacy_sample"


def test_filter_semantic_models_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_SEMANTIC_MODELS", "nonexistent")
    from solomon.semantic import store as store_mod

    store_mod.load_models(force=True)
    assert store_mod.load_models(force=True) == []


def test_ossie_read_tool_shape() -> None:
    from solomon.tools.ossie import OssieReadTool

    out = OssieReadTool().run(None, fq_name="demo_catalog.demo_schema.customers")
    assert out["status"] == "ok"
    assert "fields" in out["dataset"]


def test_ai_context_string_normalized() -> None:
    from solomon.semantic.models import AIContext, OssieSemanticModel

    model = OssieSemanticModel.model_validate(
        {
            "name": "m",
            "datasets": [{"name": "d", "source": "a.b.c", "ai_context": "plain text"}],
        }
    )
    ctx = model.datasets[0].ai_context
    assert isinstance(ctx, AIContext)
    assert ctx.instructions == "plain text"


def test_render_helpers_smoke() -> None:
    from solomon.semantic.context import (
        get_semantic_context,
        render_business_context,
        render_document_catalog,
        render_graph_schema,
        render_table_catalog,
        render_tool_hints,
    )

    get_semantic_context(force=True)
    assert render_business_context()
    assert render_table_catalog(max_chars=2000)
    assert render_graph_schema()
    assert render_document_catalog()
    assert render_tool_hints()


def test_source_catalog_without_live_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from solomon.semantic.source_catalog import build_source_catalog

    monkeypatch.setattr(
        "solomon.transport.config.get_trino_config",
        lambda: None,
    )
    monkeypatch.setattr(
        "solomon.transport.config.get_graph_config",
        lambda: None,
    )
    cat = build_source_catalog(force=True)
    assert any(t.get("in_ossie") for t in cat.tables)
    assert cat.graph.get("ossie_labels")
    assert cat.search


def test_api_semantic_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from solomon.api.main import create_app

    monkeypatch.setenv("SOLOMON_SEMANTIC_ROOT", str(FIXTURE_ROOT))
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/api/semantic/context")
        assert r.status_code == 200
        body = r.json()
        assert "datasets" in body
