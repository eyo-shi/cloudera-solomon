"""Human-readable Trino env hints for internal warehouse launcher logs."""

from __future__ import annotations


def format_internal_trino_env_hints(
    *,
    status: str | None,
    http_hosts: list[str] | None,
    internal_http: str | None = None,
    cluster_ip: str | None = None,
) -> list[str]:
    """Return copy-paste lines for Project Settings when DNS to the service fails."""
    if status != "running":
        return []
    hosts = [h.strip() for h in (http_hosts or []) if h and h.strip()]
    if not hosts and not cluster_ip:
        return []

    lines: list[str] = []
    cluster = (cluster_ip or "").strip()
    if internal_http:
        lines.append(f"Solomon TRINO_ENDPOINT (internal DNS, preferred): {internal_http}")
    if cluster:
        lines.append(
            f"Solomon TRINO_ENDPOINT (Service ClusterIP): http://{cluster}:8080"
        )
    elif hosts:
        primary = hosts[0]
        host_part, _, port_part = primary.rpartition(":")
        port = port_part if port_part.isdigit() else "8080"
        lines.append(
            f"Solomon TRINO_ENDPOINT (if DNS fails): http://{host_part}:{port}"
        )

    pod_hosts = [
        host
        for host in hosts
        if not cluster or not host.startswith(f"{cluster}:")
    ]
    if pod_hosts:
        lines.append(
            "Trino pod IP (warehouse-launcher only): "
            + ", ".join(f"http://{host}" for host in pod_hosts)
        )
    elif len(hosts) > 1:
        lines.append(f"Additional HTTP hosts: {', '.join(hosts[1:])}")

    return lines
