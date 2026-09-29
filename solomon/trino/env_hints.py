"""Human-readable Trino env hints for internal warehouse launcher logs."""

from __future__ import annotations


def format_internal_trino_env_hints(
    *,
    status: str | None,
    http_hosts: list[str] | None,
    internal_http: str | None = None,
) -> list[str]:
    """Return copy-paste lines for Project Settings when DNS to the service fails."""
    if status != "running":
        return []
    hosts = [h.strip() for h in (http_hosts or []) if h and h.strip()]
    if not hosts:
        return []

    primary = hosts[0]
    host_part, _, port_part = primary.rpartition(":")
    port = port_part if port_part.isdigit() else "8080"
    endpoint = f"http://{host_part}:{port}"

    lines = [
        f"Solomon TRINO_ENDPOINT (if DNS fails): {endpoint}",
    ]
    if internal_http:
        lines.append(f"Solomon internal HTTP (default): {internal_http}")
    if len(hosts) > 1:
        lines.append(f"Additional HTTP hosts: {', '.join(hosts[1:])}")
    return lines
