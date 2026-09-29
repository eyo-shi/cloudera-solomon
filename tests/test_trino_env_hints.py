"""Trino env hint formatting for warehouse launcher logs."""

from __future__ import annotations

from solomon.trino.env_hints import format_internal_trino_env_hints


def test_hints_empty_when_not_running() -> None:
    assert format_internal_trino_env_hints(
        status="starting",
        http_hosts=["10.0.0.20:8080"],
    ) == []


def test_hints_include_trino_endpoint_when_running() -> None:
    lines = format_internal_trino_env_hints(
        status="running",
        http_hosts=["10.0.0.20:8080", "10.96.1.5:8080"],
        internal_http="http://cml-trino-demo.namespace:8080",
    )
    assert lines[0] == "Solomon TRINO_ENDPOINT (if DNS fails): http://10.0.0.20:8080"
    assert "Solomon internal HTTP (default): http://cml-trino-demo.namespace:8080" in lines
    assert any("Additional HTTP hosts" in line for line in lines)
