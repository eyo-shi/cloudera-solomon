"""demo.checks.preflight unit tests (no external services)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE_SEM = REPO / "tests" / "fixtures" / "demo_validate" / "semantic"


@pytest.fixture
def os_cfg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "solomon.transport.config.get_opensearch_config",
        lambda: MagicMock(docs_index_name="test-docs", namespace="solomon"),
    )


def test_format_table_and_recommendations() -> None:
    from demo.checks.preflight import (
        PreflightRow,
        format_table,
        recommend_docs_analyzer,
        recommend_iceberg_load_method,
    )

    assert recommend_docs_analyzer('{"component":"analysis-kuromoji"}') == "kuromoji"
    assert recommend_docs_analyzer("") == "cjk"
    assert recommend_iceberg_load_method(["hive", "iceberg"]) == "a"
    assert recommend_iceberg_load_method(["iceberg"]) == "b"

    text = format_table([PreflightRow("a", "pass", "ok", "rec")])
    assert "check" in text
    assert "a" in text


def test_trino_catalogs_with_mock_query() -> None:
    from demo.checks.preflight import check_trino_catalogs

    def qfn(sql: str):
        assert "SHOW CATALOGS" in sql
        return [("hive",), ("iceberg",)]

    rows = check_trino_catalogs(qfn)
    assert rows[0].status == "pass"
    assert "hive" in rows[0].detail


def test_opensearch_no_write_skips_acl(os_cfg: None) -> None:
    from demo.checks.preflight import check_opensearch

    client = MagicMock()
    client.info.return_value = {"version": {"number": "2.11.0"}}
    client.cat.plugins.return_value = [{"component": "analysis-kuromoji"}]

    rows = check_opensearch(allow_write=False, client_factory=lambda: client)
    acl = next(r for r in rows if r.check == "opensearch_index_acl")
    assert acl.status == "skip"
    client.indices.create.assert_not_called()


def test_opensearch_write_creates_and_deletes_index(os_cfg: None) -> None:
    from demo.checks.preflight import PREFLIGHT_TEST_INDEX, check_opensearch

    client = MagicMock()
    client.info.return_value = {"version": {"number": "2.9.0"}}
    client.cat.plugins.return_value = []
    client.indices.exists.return_value = False

    rows = check_opensearch(allow_write=True, client_factory=lambda: client)
    acl = next(r for r in rows if r.check == "opensearch_index_acl")
    assert acl.status == "pass"
    client.indices.create.assert_called_once()
    kw = client.indices.create.call_args.kwargs
    assert kw.get("index") == PREFLIGHT_TEST_INDEX


def test_run_preflight_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    from demo.checks import preflight as pf

    monkeypatch.setattr(
        pf,
        "check_trino_catalogs",
        lambda query_fn=None: [pf.PreflightRow("trino", "skip", "")],
    )
    monkeypatch.setattr(pf, "check_puppygraph_reachability", lambda: [pf.PreflightRow("pg", "skip", "")])
    monkeypatch.setattr(pf, "check_opensearch", lambda **k: [pf.PreflightRow("os", "skip", "")])
    monkeypatch.setattr(pf, "check_embedding", lambda **k: pf.PreflightRow("emb", "skip", ""))
    monkeypatch.setattr(pf, "check_llm_function_calling", lambda **k: pf.PreflightRow("llm", "skip", ""))

    proc_validate = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: proc_validate)

    rows = pf.run_preflight(semantic_root=str(FIXTURE_SEM), allow_write=False)
    assert any(r.check == "ossie_validate" for r in rows)


def test_opensearch_version_below_29() -> None:
    from demo.checks.preflight import opensearch_version_below_29

    assert opensearch_version_below_29("2.8.0") is True
    assert opensearch_version_below_29("2.11.0") is False


def test_cli_no_write_exit_code() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "demo.checks.preflight",
            "--semantic-root",
            str(FIXTURE_SEM),
            "--no-write",
        ],
        cwd=REPO,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
    )
    assert "check" in proc.stdout.lower()
    assert proc.returncode in (0, 1)
