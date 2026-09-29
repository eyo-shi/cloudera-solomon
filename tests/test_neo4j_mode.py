"""Neo4j mode switching (internal vs external)."""

from __future__ import annotations

import pytest

from solomon.graph.config import get_neo4j_config
from solomon.graph.mode import is_internal_neo4j_mode, neo4j_mode
from solomon.graph.neo4j_endpoints_file import write_endpoints

_NEO4J_ENV_KEYS = (
    "NEO4J_MODE",
    "SOLOMON_NEO4J_MODE",
    "NEO4J_URI",
    "NEO4J_EXTERNAL_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "NEO4J_ENDPOINTS_FILE",
    "SOLOMON_NEO4J_ENDPOINTS_FILE",
)


@pytest.fixture(autouse=True)
def _clean_neo4j_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _NEO4J_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_default_mode_is_internal() -> None:
    assert neo4j_mode() == "internal"
    assert is_internal_neo4j_mode()


def test_legacy_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLOMON_NEO4J_MODE", "external")
    assert neo4j_mode() == "external"


def test_internal_mode_reads_endpoints_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_MODE", "internal")
    endpoints = tmp_path / "neo4j_endpoints.json"
    monkeypatch.setenv("NEO4J_ENDPOINTS_FILE", str(endpoints))
    write_endpoints(
        {
            "bolt_hosts": ["10.0.0.10"],
            "internal_bolt": "bolt://cml-neo4j-demo.namespace:7687",
        }
    )
    cfg = get_neo4j_config()
    assert cfg is not None
    assert cfg.uri == "bolt://10.0.0.10:7687"


def test_external_mode_requires_neo4j_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_MODE", "external")
    assert get_neo4j_config() is None
    monkeypatch.setenv("NEO4J_URI", "bolt://external-neo4j.example.com:7687")
    cfg = get_neo4j_config()
    assert cfg is not None
    assert cfg.uri == "bolt://external-neo4j.example.com:7687"


def test_internal_mode_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEO4J_MODE", "internal")
    monkeypatch.setenv("NEO4J_URI", "bolt://override:7687")
    cfg = get_neo4j_config()
    assert cfg is not None
    assert cfg.uri == "bolt://override:7687"
