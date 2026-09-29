"""Shared Neo4j endpoints file tests."""

from __future__ import annotations

import json

from solomon.graph.neo4j_endpoints_file import load_bolt_uris, write_endpoints


def test_load_bolt_uris_from_shared_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "neo4j_endpoints.json"
    path.write_text(
        json.dumps(
            {
                "bolt_hosts": ["10.43.10.5", "10.42.1.17"],
                "internal_bolt": "bolt://cml-neo4j-abc.mlx-user-2:7687",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEO4J_ENDPOINTS_FILE", str(path))

    uris = load_bolt_uris()
    assert uris[0] == "bolt://10.43.10.5:7687"
    assert "bolt://10.42.1.17:7687" in uris
    assert "bolt://cml-neo4j-abc.mlx-user-2:7687" in uris


def test_write_endpoints_round_trip(tmp_path, monkeypatch) -> None:
    path = tmp_path / ".solomon" / "neo4j_endpoints.json"
    monkeypatch.setenv("NEO4J_ENDPOINTS_FILE", str(path))

    written = write_endpoints({"bolt_hosts": ["10.42.1.17"]})
    assert written == path
    assert load_bolt_uris() == ["bolt://10.42.1.17:7687"]
