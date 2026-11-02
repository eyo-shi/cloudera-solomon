"""Semantic level: Ossie validate, examples, router, parquet, domain-neutral."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from demo.loader.ossie_domain import validate_semantic_root
from demo.validate.model import CheckResult
from demo.validate.ossie_examples import all_examples
from demo.validate.parquet_schema import check_parquet_vs_ossie
from demo.validate.scenario import list_questions, load_scenario


def run_semantic(domain_dir: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    semantic_root = domain_dir / "semantic"
    scenario = load_scenario(domain_dir)

    try:
        validate_semantic_root(semantic_root)
        results.append(CheckResult(name="solomon.semantic validate", ok=True, category="semantic"))
    except RuntimeError as exc:
        results.append(
            CheckResult(name="solomon.semantic validate", ok=False, detail=str(exc), category="semantic")
        )

    examples = set(all_examples(semantic_root))
    for q in list_questions(scenario):
        prompt = str(q.get("prompt") or "").strip()
        if not prompt:
            continue
        ok = prompt in examples
        results.append(
            CheckResult(
                name=f"scenario_example:{q.get('id')}",
                ok=ok,
                detail="found in ai_context.examples" if ok else "missing from Ossie examples",
                category="semantic",
            )
        )

    import os

    os.environ["SOLOMON_SEMANTIC_ROOT"] = str(semantic_root)
    os.environ["SOLOMON_SEMANTIC_MODELS"] = ""
    from solomon.semantic import context as ctx_mod
    from solomon.semantic import store as store_mod

    store_mod.load_models(force=True)
    ctx_mod._cache_ctx = None

    from solomon.router.crew import heuristic_classify

    for q in list_questions(scenario):
        prompt = str(q.get("prompt") or "").strip()
        if not prompt:
            continue
        intent = heuristic_classify(prompt).intent
        ok = intent == "KNOWLEDGE_RAG"
        results.append(
            CheckResult(
                name=f"router_heuristic:{q.get('id')}",
                ok=ok,
                detail=f"intent={intent}",
                category="semantic",
            )
        )

    results.extend(check_parquet_vs_ossie(domain_dir, validate_semantic=False))

    script = Path(__file__).resolve().parents[3] / "scripts" / "check_domain_neutral.py"
    if script.is_file():
        proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        ok = proc.returncode == 0
        results.append(
            CheckResult(
                name="check_domain_neutral",
                ok=ok,
                detail=(proc.stdout or proc.stderr).strip()[:500],
                category="semantic",
            )
        )

    return results


__all__ = ["run_semantic"]
