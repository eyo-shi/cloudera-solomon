"""Resolve Neo4j Bolt endpoints via Kubernetes when cluster DNS is unavailable."""

from __future__ import annotations

from pathlib import Path


def current_k8s_namespace() -> str | None:
    try:
        text = Path(
            "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
        ).read_text(encoding="utf-8")
        return text.strip() or None
    except OSError:
        return None


def parse_cml_neo4j_service(host: str) -> tuple[str | None, str | None]:
    """``cml-neo4j-<id>.mlx-user-<n>`` から service / namespace を取り出す。"""
    parts = host.lower().split(".")
    if not parts or not parts[0].startswith("cml-neo4j-"):
        return None, None
    service = parts[0]
    namespace = None
    if len(parts) >= 2 and parts[1].startswith("mlx-user-"):
        namespace = parts[1]
    return service, namespace


def resolve_bolt_uris_from_k8s(
    service_name: str,
    *,
    namespace: str | None = None,
    port: int = 7687,
) -> list[str]:
    """Service ClusterIP / Endpoints から bolt:// URI を組み立てる。"""
    ns = (namespace or current_k8s_namespace() or "").strip()
    if not ns:
        return []

    try:
        from kubernetes import client, config
        from kubernetes.client.rest import ApiException
    except ImportError:
        return []

    try:
        config.load_incluster_config()
    except config.ConfigException:
        return []

    api = client.CoreV1Api()
    uris: list[str] = []
    seen: set[str] = set()

    def add_host(host: str) -> None:
        host = host.strip()
        if not host or host in seen:
            return
        seen.add(host)
        uris.append(f"bolt://{host}:{port}")

    try:
        service = api.read_namespaced_service(name=service_name, namespace=ns)
        cluster_ip = (service.spec.cluster_ip or "").strip()
        if cluster_ip and cluster_ip.lower() != "none":
            add_host(cluster_ip)
    except ApiException:
        pass

    try:
        endpoints = api.read_namespaced_endpoints(name=service_name, namespace=ns)
        for subset in endpoints.subsets or []:
            for address in subset.addresses or []:
                if address.ip:
                    add_host(address.ip)
    except ApiException:
        pass

    return uris
