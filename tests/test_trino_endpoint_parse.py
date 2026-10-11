"""Trino host / URL parsing."""

from __future__ import annotations

from solomon.transport.config import _parse_trino_host_port_scheme


def test_parse_trino_full_https_url() -> None:
    host, port, scheme = _parse_trino_host_port_scheme(
        "https://default-trino-aws.dw-go01-demo-aws.ylcu-atmi.cloudera.site:443"
    )
    assert host == "default-trino-aws.dw-go01-demo-aws.ylcu-atmi.cloudera.site"
    assert port == 443
    assert scheme == "https"


def test_parse_trino_host_with_port() -> None:
    host, port, scheme = _parse_trino_host_port_scheme(
        "trino.example.com:8443",
        default_scheme="https",
    )
    assert host == "trino.example.com"
    assert port == 8443
