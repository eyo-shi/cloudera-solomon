"""demo/*/semantic の Ossie 例題が heuristic で KNOWLEDGE_RAG になること (データ駆動)。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from solomon.router.crew import heuristic_classify

_REPO = Path(__file__).resolve().parents[1]


def _demo_semantic_models() -> list[Path]:
    roots: list[Path] = []
    demo = _REPO / "demo"
    if not demo.is_dir():
        return []
    for domain_dir in sorted(demo.iterdir()):
        models_dir = domain_dir / "semantic" / "models"
        if models_dir.is_dir():
            roots.extend(sorted(models_dir.glob("*.yaml")))
            roots.extend(sorted(models_dir.glob("*.yml")))
    return roots


def _collect_examples(path: Path) -> list[str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    items = raw.get("semantic_model")
    if items is None:
        models = [raw]
    elif isinstance(items, list):
        models = items
    else:
        models = [items]
    out: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        ai = model.get("ai_context")
        if isinstance(ai, dict):
            out.extend(str(x) for x in ai.get("examples") or [])
        for ds in model.get("datasets") or []:
            if not isinstance(ds, dict):
                continue
            dai = ds.get("ai_context")
            if isinstance(dai, dict):
                out.extend(str(x) for x in dai.get("examples") or [])
        for ext in model.get("custom_extensions") or []:
            if str(ext.get("vendor_name", "")).upper() != "SOLOMON":
                continue
            data = ext.get("data")
            if isinstance(data, dict):
                for gx in data.get("graph_examples") or []:
                    if isinstance(gx, dict) and gx.get("question"):
                        out.append(str(gx["question"]))
    return [q.strip() for q in out if q and q.strip()]


_demo_models = _demo_semantic_models()


@pytest.mark.skipif(not _demo_models, reason="no demo/*/semantic/models")
@pytest.mark.parametrize("model_path", _demo_models, ids=lambda p: p.name)
def test_demo_ossie_examples_route_to_knowledge_rag(
    model_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semantic_root = model_path.parent.parent
    monkeypatch.setenv("SOLOMON_SEMANTIC_ROOT", str(semantic_root))
    from solomon.semantic import context as ctx_mod
    from solomon.semantic import store as store_mod
    from solomon.semantic import source_catalog as sc_mod

    store_mod.load_models(force=True)
    ctx_mod._cache_ctx = None
    sc_mod._cache_catalog = None

    examples = _collect_examples(model_path)
    if not examples:
        pytest.skip("no ai_context.examples in model")

    for question in examples[:15]:
        result = heuristic_classify(question)
        assert result.intent == "KNOWLEDGE_RAG", (
            f"expected KNOWLEDGE_RAG for example {question!r}, got {result.intent}"
        )
