"""Neo4j connection URI helpers for CML neo4j-launcher."""

from __future__ import annotations

import os
from urllib.parse import urlparse

_BROWSER_HOST_MARKERS = (".cloudera.site",)
_EXTERNAL_BOLT_HOST_MARKERS = (".elb.amazonaws.com", ".amazonaws.com")


def _is_browser_neo4j_host(host: str) -> bool:
    lowered = host.lower()
    return any(marker in lowered for marker in _BROWSER_HOST_MARKERS)


def _is_external_bolt_neo4j_host(host: str) -> bool:
    lowered = host.lower()
    return any(marker in lowered for marker in _EXTERNAL_BOLT_HOST_MARKERS)


def _is_cml_internal_neo4j_host(host: str) -> bool:
    lowered = host.lower()
    return lowered.startswith("cml-neo4j-") or ".mlx-user-" in lowered


def _parse_uri(uri: str) -> tuple[str, str, int, str]:
    text = uri.strip()
    if "://" not in text:
        text = f"bolt://{text}"
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    port = parsed.port or 7687
    scheme = (parsed.scheme or "bolt").lower()
    return text, host, port, scheme


def iter_neo4j_connection_uris(
    uri: str,
    *,
    internal_uri: str | None = None,
) -> list[str]:
    """Build URIs to try when connecting from a CML job."""
    internal_uri = (internal_uri or os.environ.get("NEO4J_INTERNAL_URI", "")).strip() or None

    _, host, port, scheme = _parse_uri(uri)
    if not host and not internal_uri:
        return [uri.strip() if "://" in uri else f"bolt://{uri.strip()}"]

    seen: set[str] = set()
    ordered: list[str] = []

    def add(candidate: str) -> None:
        normalized = candidate.strip()
        if "://" not in normalized:
            normalized = f"bolt://{normalized}"
        if normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)

    def add_host(candidate_scheme: str, candidate_host: str) -> None:
        add(f"{candidate_scheme}://{candidate_host}:{port}")

    if internal_uri:
        add(internal_uri)

    if host and _is_cml_internal_neo4j_host(host):
        add_host(scheme, host)
        parts = host.split(".")
        service = parts[0]
        if len(parts) >= 2 and not host.endswith(".svc.cluster.local"):
            namespace = parts[1]
            add_host(scheme, f"{service}.{namespace}.svc.cluster.local")
        if service and service != host:
            add_host(scheme, service)
        return ordered

    if host and _is_browser_neo4j_host(host):
        return ordered

    if host and _is_external_bolt_neo4j_host(host):
        add_host(scheme, host)
        return ordered

    if host:
        add_host(scheme, host)
        if scheme in {"bolt+ssc", "bolt+s", "neo4j+ssc", "neo4j+s"}:
            add_host("bolt", host)

    if host and "neo4j-launcher" in host:
        add_host("bolt", "neo4j-launcher")

    return ordered or [uri.strip()]


def validate_neo4j_uri_for_ingest(uri: str) -> None:
    lowered = uri.lower()
    if any(marker in lowered for marker in ("replace_from_application_log", "replace_from_neo4j")):
        raise ValueError(
            "NEO4J_URI is still the placeholder. Once the co-located Neo4j Launcher "
            "Application is Running, copy the Internal Bolt URI from its Application Log "
            "into Project Settings > Advanced > Environment Variables."
        )
    if ".cloudera.site" in lowered:
        raise ValueError(
            "NEO4J_URI is a neo4j-launcher browser URL (*.cloudera.site), not Bolt. "
            "Use Internal Bolt (same project) or External Bolt (cross project) "
            "from the neo4j-launcher Application Log."
        )


def format_neo4j_connection_help(configured_uri: str, errors: list[str]) -> str:
    internal_example = (
        os.environ.get("NEO4J_INTERNAL_URI", "").strip()
        or "bolt://cml-neo4j-<hash>.mlx-user-<id>:7687"
    )
    attempts = "\n".join(errors) if errors else "  (no attempts recorded)"
    return (
        f"Could not connect to Neo4j (configured: {configured_uri}).\n"
        f"Attempts:\n{attempts}\n"
        "CML neo4j-launcher checklist:\n"
        "  1. neo4j-launcher application is Running (Applications page)\n"
        "  2. Copy a Bolt URL from neo4j-launcher Application Log into NEO4J_URI\n"
        "     - Same AMP project as neo4j-launcher: Internal Bolt\n"
        f"       Example: {internal_example}\n"
        "     - Different AMP project (cross-namespace): External Bolt (ELB)\n"
        "       Example: bolt://<lb-id>.<region>.elb.amazonaws.com:7687\n"
        "     Do not use browser URL (*.cloudera.site) — that is not a Bolt endpoint\n"
        "  3. NEO4J_PASSWORD is the password from neo4j-launcher startup\n"
        "  4. NEO4J_USERNAME is usually neo4j"
    )
