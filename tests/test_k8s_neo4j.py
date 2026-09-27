"""Kubernetes Neo4j endpoint resolution tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from solomon.graph.k8s_neo4j import parse_cml_neo4j_service, resolve_bolt_uris_from_k8s


def test_parse_cml_neo4j_service() -> None:
    service, namespace = parse_cml_neo4j_service(
        "cml-neo4j-uc07nlf42vot6jz5.mlx-user-2"
    )
    assert service == "cml-neo4j-uc07nlf42vot6jz5"
    assert namespace == "mlx-user-2"


def test_resolve_bolt_uris_from_k8s_uses_cluster_ip_and_pod_ip(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "solomon.graph.k8s_neo4j.current_k8s_namespace",
        lambda: "mlx-user-2",
    )

    service = SimpleNamespace(spec=SimpleNamespace(cluster_ip="10.43.10.5"))
    endpoints = SimpleNamespace(
        subsets=[
            SimpleNamespace(
                addresses=[SimpleNamespace(ip="10.42.1.17")],
            )
        ]
    )

    api = MagicMock()
    api.read_namespaced_service.return_value = service
    api.read_namespaced_endpoints.return_value = endpoints

    with patch("kubernetes.config.load_incluster_config"), patch(
        "kubernetes.client.CoreV1Api",
        return_value=api,
    ):
        uris = resolve_bolt_uris_from_k8s("cml-neo4j-abc", namespace="mlx-user-2")

    assert uris == ["bolt://10.43.10.5:7687", "bolt://10.42.1.17:7687"]
