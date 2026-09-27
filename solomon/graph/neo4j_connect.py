"""Neo4j connection URI helpers for CML neo4j-launcher."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from solomon.graph.k8s_neo4j import parse_cml_neo4j_service, resolve_bolt_uris_from_k8s
from solomon.graph.neo4j_endpoints_file import load_bolt_uris

_BROWSER_HOST_MARKERS = (".cloudera.site",)
_EXTERNAL_BOLT_HOST_MARKERS = (".elb.amazonaws.com", ".amazonaws.com")
_OPTIONAL_UNSET_VALUE = "-"
_PLACEHOLDER_MARKERS = ("replace_from_application_log", "replace_from_neo4j")


def _normalize_uri_seed(raw: str | None) -> str | None:
    """CML optional env の ``-`` や placeholder を接続候補から除外する。"""
    text = (raw or "").strip()
    if not text or text == _OPTIONAL_UNSET_VALUE:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return None
    return text


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


def _configured_neo4j_uri_seeds(
    uri: str,
    *,
    internal_uri: str | None = None,
) -> list[str]:
    """Primary URI plus optional NEO4J_INTERNAL_URI / NEO4J_EXTERNAL_URI overrides."""
    seeds: list[str] = []
    for shared_uri in load_bolt_uris():
        if shared_uri not in seeds:
            seeds.append(shared_uri)
    bolt_host_override = _normalize_uri_seed(os.environ.get("NEO4J_BOLT_HOST", ""))
    if bolt_host_override:
        if "://" in bolt_host_override:
            seeds.append(bolt_host_override)
        elif ":" in bolt_host_override:
            seeds.append(f"bolt://{bolt_host_override}")
        else:
            seeds.append(f"bolt://{bolt_host_override}:7687")
    for candidate in (
        uri,
        internal_uri or os.environ.get("NEO4J_INTERNAL_URI", ""),
        os.environ.get("NEO4J_EXTERNAL_URI", ""),
    ):
        text = _normalize_uri_seed(candidate)
        if text and text not in seeds:
            seeds.append(text)
    return seeds


def _expand_uri_seed(seed: str) -> list[str]:
    """Expand one configured URI into DNS / scheme variants to try."""
    _, host, port, scheme = _parse_uri(seed)
    if not host:
        text = seed.strip()
        return [text if "://" in text else f"bolt://{text}"]

    expanded: list[str] = []

    def add(candidate_scheme: str, candidate_host: str) -> None:
        expanded.append(f"{candidate_scheme}://{candidate_host}:{port}")

    if _is_cml_internal_neo4j_host(host):
        add(scheme, host)
        service, namespace = parse_cml_neo4j_service(host)
        if service and namespace and not host.endswith(".svc.cluster.local"):
            add(scheme, f"{service}.{namespace}.svc.cluster.local")
        if service:
            add(scheme, service)
            expanded.extend(
                resolve_bolt_uris_from_k8s(
                    service,
                    namespace=namespace,
                    port=port,
                )
            )
        return expanded

    if _is_browser_neo4j_host(host):
        return []

    if _is_external_bolt_neo4j_host(host):
        add(scheme, host)
        return expanded

    add(scheme, host)
    if scheme in {"bolt+ssc", "bolt+s", "neo4j+ssc", "neo4j+s"}:
        add("bolt", host)
    if "neo4j-launcher" in host:
        add("bolt", "neo4j-launcher")
    return expanded


def iter_neo4j_connection_uris(
    uri: str,
    *,
    internal_uri: str | None = None,
) -> list[str]:
    """Build URIs to try when connecting from a CML job."""
    seeds = _configured_neo4j_uri_seeds(uri, internal_uri=internal_uri)
    if not seeds:
        text = uri.strip()
        return [text if "://" in text else f"bolt://{text}"]

    seen: set[str] = set()
    ordered: list[str] = []
    for seed in seeds:
        for candidate in _expand_uri_seed(seed):
            normalized = candidate.strip()
            if "://" not in normalized:
                normalized = f"bolt://{normalized}"
            if normalized not in seen:
                seen.add(normalized)
                ordered.append(normalized)
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


def _env_example(name: str, fallback: str) -> str:
    return _normalize_uri_seed(os.environ.get(name, "")) or fallback


def format_neo4j_connection_help(configured_uri: str, errors: list[str]) -> str:
    internal_example = _env_example(
        "NEO4J_INTERNAL_URI",
        "bolt://cml-neo4j-<hash>.mlx-user-<id>:7687",
    )
    external_example = _env_example(
        "NEO4J_EXTERNAL_URI",
        "bolt://<lb-id>.<region>.elb.amazonaws.com:7687",
    )
    attempts = "\n".join(errors) if errors else "  (no attempts recorded)"
    return (
        f"Could not connect to Neo4j (configured: {configured_uri}).\n"
        f"Attempts:\n{attempts}\n"
        "CML neo4j-launcher checklist:\n"
        "  1. neo4j-launcher application is Running (Applications page)\n"
        "  2. Copy Bolt URLs from neo4j-launcher Application Log\n"
        "     - Same AMP project: set NEO4J_URI to Internal Bolt\n"
        f"       Example: {internal_example}\n"
        "     - Internal DNS fails (Name or service not known): set NEO4J_URI or\n"
        "       NEO4J_EXTERNAL_URI to External Bolt (ELB) and restart Solomon\n"
        f"       Example: {external_example}\n"
        "     Do not use browser URL (*.cloudera.site) — that is not a Bolt endpoint\n"
        "  3. Restart neo4j-launcher so it writes .solomon/neo4j_endpoints.json\n"
        "     (ClusterIP / Pod IP for Solomon when DNS is unavailable)\n"
        "  4. Manual override: NEO4J_BOLT_HOST=<pod-ip-or-cluster-ip> (optional)\n"
        "  5. After changing env vars, restart the Solomon Application (not only neo4j-launcher)\n"
        "  6. NEO4J_PASSWORD is the password from neo4j-launcher startup\n"
        "  7. NEO4J_USERNAME is usually neo4j"
    )
