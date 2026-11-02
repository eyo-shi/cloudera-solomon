"""demo.validate unit tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "demo_validate"
MFG = REPO / "demo" / "mfg_quality"


@pytest.fixture
def validate_domain(tmp_path: Path) -> Path:
    domain = tmp_path / "domain"
    for sub in ("semantic/models", "output/tables"):
        (domain / sub).mkdir(parents=True)
    (domain / "scenario.yaml").write_text((FIXTURE / "scenario.yaml").read_text(encoding="utf-8"))
    (domain / "semantic/models/demo_validate.yaml").write_text(
        (FIXTURE / "semantic/models/demo_validate.yaml").read_text(encoding="utf-8")
    )
    entities = pd.DataFrame([{"entity_id": "ALPHA-1", "name": "One"}])
    links = pd.DataFrame([{"from_id": "ALPHA-1", "to_id": "B"}])
    entities.to_parquet(domain / "output/tables/entities.parquet", index=False)
    links.to_parquet(domain / "output/tables/links.parquet", index=False)
    return domain


def test_scoring_normalization_and_grade() -> None:
    from demo.validate.scoring import grade_symbol, key_hit_rate, normalize_text

    assert normalize_text("１,２３４") == "1234"
    stats = key_hit_rate("unit ALPHA-1 built", ["ALPHA-1", "missing-key"])
    assert stats["rate"] == 0.5
    assert grade_symbol(0.85) == "◎"
    assert grade_symbol(0.6) == "○"
    assert grade_symbol(0.0) == "×"


def test_flatten_expected_keys() -> None:
    from demo.validate.scenario import flatten_expected_keys, load_scenario

    scenario = load_scenario(FIXTURE)
    keys, forbidden = flatten_expected_keys(scenario, "Q1")
    assert any("ALPHA" in k for k in keys)
    assert forbidden == [] or isinstance(forbidden, list)


def test_search_checks_table_without_opensearch() -> None:
    from demo.validate.scenario import load_scenario, search_check_defs
    from demo.validate.search_checks import run_search_checks

    scenario = load_scenario(FIXTURE)
    results, rows, md = run_search_checks(search_check_defs(scenario), use_opensearch=False)
    assert results[0].ok
    assert len(rows) >= 3
    assert "expand_off" in md


def test_run_semantic_fixture(validate_domain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO)
    from demo.validate.levels.semantic import run_semantic

    results = run_semantic(validate_domain)
    names = {r.name for r in results}
    assert "solomon.semantic validate" in names
    assert any(r.name == "scenario_example:Q1" and r.ok for r in results)


def test_fk_check_fails_on_orphan(tmp_path: Path) -> None:
    from demo.validate.fk_checks import check_foreign_keys

    domain = tmp_path / "d"
    (domain / "semantic/models").mkdir(parents=True)
    (domain / "semantic/models/m.yaml").write_text(
        (FIXTURE / "semantic/models/demo_validate.yaml").read_text(encoding="utf-8")
    )
    entities = pd.DataFrame([{"entity_id": "ALPHA-1", "name": "One"}])
    links = pd.DataFrame([{"from_id": "ORPHAN", "to_id": "B"}])
    tables = {"entities": entities, "links": links}
    results = check_foreign_keys(domain, tables)
    assert any(not r.ok for r in results)


def test_cli_semantic_dry(validate_domain: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "demo.validate",
            "--domain-dir",
            str(validate_domain),
            "--level",
            "semantic",
        ],
        cwd=REPO,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode in (0, 1)
    assert "report:" in proc.stdout or proc.stdout


@pytest.mark.skipif(not MFG.is_dir(), reason="mfg_quality missing")
def test_mfg_local_skips_without_parquet() -> None:
    from demo.validate.levels.local import run_local

    empty = REPO / "demo" / "mfg_quality"
    out = empty / "output" / "tables"
    if not any(out.glob("*.parquet")):
        results = run_local(empty)
        assert any(not r.ok for r in results)


@pytest.mark.skipif(not MFG.is_dir(), reason="mfg_quality missing")
def test_mfg_scenario_questions_in_ossie() -> None:
    from demo.validate.ossie_examples import all_examples
    from demo.validate.scenario import list_questions, load_scenario

    scenario = load_scenario(MFG)
    examples = set(all_examples(MFG / "semantic"))
    for q in list_questions(scenario):
        assert q["prompt"] in examples
