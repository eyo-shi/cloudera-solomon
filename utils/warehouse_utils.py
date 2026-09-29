"""Kubernetes supervisor for co-located Trino + DuckDB (internal warehouse demo mode)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from kubernetes import client, config
from kubernetes.client.rest import ApiException

config.load_incluster_config()

TRINO_IMAGE = os.getenv("TRINO_IMAGE") or "trinodb/trino:476"
TRINO_SERVICE_TYPE = os.getenv("TRINO_SERVICE_TYPE") or "ClusterIP"
TRINO_MEMORY = os.getenv("TRINO_MEMORY") or "2Gi"
TRINO_JAVA_OPTS = os.getenv("TRINO_JAVA_OPTS") or "-Xmx1G"
DUCKDB_INIT_IMAGE = os.getenv("DUCKDB_INIT_IMAGE") or "python:3.12-slim"
DUCKDB_FILE = os.getenv("DUCKDB_FILE") or "/data/solomon.duckdb"
TRINO_STARTUP_TIMEOUT_SECONDS = int(os.getenv("TRINO_STARTUP_TIMEOUT_SECONDS") or "900")
TRINO_CATALOG_NAME = os.getenv("TRINO_CATALOG_NAME") or "iceberg"

_supervisor_state: dict = {"phase": "initializing", "error": None}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized in ("1", "true", "yes", "on")


TRINO_USE_PVC = _env_bool("TRINO_USE_PVC", default=False)


def get_current_namespace() -> str:
    with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r") as f:
        return f.read().strip()


def get_engine_id() -> str:
    return (os.getenv("CDSW_ENGINE_ID") or "local").strip()


def get_service_name() -> str:
    return f"cml-trino-{get_engine_id()}"


def get_deployment_name() -> str:
    return f"warehouse-{get_engine_id()}"


def get_configmap_name() -> str:
    return f"warehouse-config-{get_engine_id()}"


def get_owner_reference() -> client.V1OwnerReference:
    pod_name = (os.getenv("HOSTNAME") or "").strip()
    pod = client.CoreV1Api().read_namespaced_pod(
        name=pod_name,
        namespace=get_current_namespace(),
    )
    return client.V1OwnerReference(
        api_version="v1",
        kind="Pod",
        name=pod_name,
        uid=pod.metadata.uid,
    )


def _normalize_memory(value: str) -> str:
    normalized = value.strip()
    if normalized.isdigit():
        return f"{normalized}Gi"
    return normalized


def _duckdb_init_script() -> str:
    path = Path(__file__).resolve().parent.parent / "warehouse" / "duckdb_init.py"
    return path.read_text(encoding="utf-8")


def _trino_config_properties() -> str:
    return "\n".join(
        [
            "coordinator=true",
            "node-scheduler.include-coordinator=true",
            "http-server.http.port=8080",
            "discovery.uri=http://localhost:8080",
            "",
        ]
    )


def _trino_catalog_properties() -> str:
    return "\n".join(
        [
            "connector.name=duckdb",
            f"connection-url=jdbc:duckdb:{DUCKDB_FILE}",
            "",
        ]
    )


def ensure_configmaps() -> None:
    core = client.CoreV1Api()
    namespace = get_current_namespace()
    body = client.V1ConfigMap(
        api_version="v1",
        metadata=client.V1ObjectMeta(
            name=get_configmap_name(),
            namespace=namespace,
            owner_references=[get_owner_reference()],
        ),
        data={
            "config.properties": _trino_config_properties(),
            f"{TRINO_CATALOG_NAME}.properties": _trino_catalog_properties(),
            "duckdb_init.py": _duckdb_init_script(),
        },
    )
    try:
        core.create_namespaced_config_map(namespace=namespace, body=body)
        print(f"Created warehouse ConfigMap {get_configmap_name()}")
    except ApiException as exc:
        if exc.status != 409:
            raise
        core.replace_namespaced_config_map(
            name=get_configmap_name(),
            namespace=namespace,
            body=body,
        )
        print(f"Updated warehouse ConfigMap {get_configmap_name()}")


def _data_volume() -> client.V1Volume:
    volume = client.V1Volume(name="warehouse-data")
    if TRINO_USE_PVC:
        pod_name = (os.getenv("HOSTNAME") or "").strip()
        pod_spec = client.CoreV1Api().read_namespaced_pod(
            name=pod_name,
            namespace=get_current_namespace(),
        )
        claim_name = None
        for mount in pod_spec.spec.containers[0].volume_mounts or []:
            if mount.mount_path == "/home/cdsw":
                for vol in pod_spec.spec.volumes or []:
                    if vol.name == mount.name and vol.persistent_volume_claim:
                        claim_name = vol.persistent_volume_claim.claim_name
                        break
        if not claim_name:
            raise RuntimeError("PVC claim for /home/cdsw not found")
        volume.persistent_volume_claim = client.V1PersistentVolumeClaimVolumeSource(
            claim_name=claim_name
        )
    else:
        volume.empty_dir = client.V1EmptyDirVolumeSource()
    return volume


def create_deployment_spec() -> client.V1Deployment:
    namespace = get_current_namespace()
    memory = _normalize_memory(TRINO_MEMORY)
    data_volume = _data_volume()
    data_mount = client.V1VolumeMount(name="warehouse-data", mount_path="/data")
    if TRINO_USE_PVC:
        data_mount.sub_path = "warehouse-volume"

    config_volume = client.V1Volume(
        name="warehouse-config",
        config_map=client.V1ConfigMapVolumeSource(name=get_configmap_name()),
    )

    init_container = client.V1Container(
        name="duckdb-init",
        image=DUCKDB_INIT_IMAGE,
        image_pull_policy="IfNotPresent",
        command=["/bin/sh", "-c"],
        args=[
            "pip install -q duckdb && python /config/duckdb_init.py "
            f"{DUCKDB_FILE}"
        ],
        volume_mounts=[
            data_mount,
            client.V1VolumeMount(name="warehouse-config", mount_path="/config"),
        ],
    )

    trino_container = client.V1Container(
        name="trino",
        image=TRINO_IMAGE,
        image_pull_policy="IfNotPresent",
        ports=[client.V1ContainerPort(container_port=8080, name="http")],
        env=[client.V1EnvVar(name="JAVA_TOOL_OPTIONS", value=TRINO_JAVA_OPTS)],
        resources=client.V1ResourceRequirements(
            requests={"cpu": "500m", "memory": memory},
            limits={"cpu": "2", "memory": memory},
        ),
        startup_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/v1/info", port=8080),
            period_seconds=10,
            failure_threshold=60,
        ),
        readiness_probe=client.V1Probe(
            http_get=client.V1HTTPGetAction(path="/v1/info", port=8080),
            period_seconds=10,
            failure_threshold=30,
        ),
        volume_mounts=[
            data_mount,
            client.V1VolumeMount(
                name="warehouse-config",
                mount_path="/etc/trino/config.properties",
                sub_path="config.properties",
            ),
            client.V1VolumeMount(
                name="warehouse-config",
                mount_path=f"/etc/trino/catalog/{TRINO_CATALOG_NAME}.properties",
                sub_path=f"{TRINO_CATALOG_NAME}.properties",
            ),
        ],
    )

    pod_spec = client.V1PodSpec(
        init_containers=[init_container],
        containers=[trino_container],
        volumes=[data_volume, config_volume],
    )

    return client.V1Deployment(
        api_version="apps/v1",
        metadata=client.V1ObjectMeta(
            name=get_deployment_name(),
            labels={"app": get_deployment_name()},
            namespace=namespace,
        ),
        spec=client.V1DeploymentSpec(
            replicas=1,
            progress_deadline_seconds=900,
            selector=client.V1LabelSelector(match_labels={"app": get_deployment_name()}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={"app": get_deployment_name()},
                    annotations={"sidecar.istio.io/inject": "false"},
                ),
                spec=pod_spec,
            ),
        ),
    )


def create_service_spec() -> client.V1Service:
    return client.V1Service(
        api_version="v1",
        metadata=client.V1ObjectMeta(
            name=get_service_name(),
            namespace=get_current_namespace(),
            owner_references=[get_owner_reference()],
        ),
        spec=client.V1ServiceSpec(
            type=TRINO_SERVICE_TYPE,
            selector={"app": get_deployment_name()},
            ports=[client.V1ServicePort(name="http", port=8080, target_port=8080)],
        ),
    )


def deploy_warehouse() -> None:
    ensure_configmaps()
    apps = client.AppsV1Api()
    core = client.CoreV1Api()
    namespace = get_current_namespace()
    deployment = create_deployment_spec()
    try:
        apps.create_namespaced_deployment(namespace=namespace, body=deployment)
        print(f"Created warehouse deployment {get_deployment_name()}")
    except ApiException as exc:
        if exc.status != 409:
            raise
        apps.replace_namespaced_deployment(
            name=get_deployment_name(),
            namespace=namespace,
            body=deployment,
        )
        print(f"Updated warehouse deployment {get_deployment_name()}")

    service = create_service_spec()
    try:
        core.create_namespaced_service(namespace=namespace, body=service)
        print(f"Created warehouse service {get_service_name()}")
    except ApiException as exc:
        if exc.status != 409:
            raise
        core.replace_namespaced_service(
            name=get_service_name(),
            namespace=namespace,
            body=service,
        )
        print(f"Updated warehouse service {get_service_name()}")


def _list_warehouse_pods() -> list[client.V1Pod]:
    core = client.CoreV1Api()
    pods = core.list_namespaced_pod(
        namespace=get_current_namespace(),
        label_selector=f"app={get_deployment_name()}",
    )
    return pods.items or []


def _pod_status_summary() -> str | None:
    pods = _list_warehouse_pods()
    if not pods:
        return "no pod"
    pod = pods[0]
    phase = pod.status.phase or "Unknown"
    if pod.status.init_container_statuses:
        init = pod.status.init_container_statuses[0]
        waiting = init.state.waiting
        if waiting and waiting.reason:
            return f"init/{waiting.reason}"
    if pod.status.container_statuses:
        waiting = pod.status.container_statuses[0].state.waiting
        if waiting and waiting.reason:
            return f"{phase}/{waiting.reason}"
    return phase


def _pod_logs(tail_lines: int = 120) -> str | None:
    pods = _list_warehouse_pods()
    if not pods:
        return None
    try:
        return client.CoreV1Api().read_namespaced_pod_log(
            name=pods[0].metadata.name,
            namespace=get_current_namespace(),
            tail_lines=tail_lines,
            container="trino",
        )
    except ApiException:
        return None


def _collect_http_hosts() -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()

    def add(host: str | None) -> None:
        text = (host or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        hosts.append(text)

    for pod in _list_warehouse_pods():
        if pod.status.pod_ip:
            add(f"{pod.status.pod_ip}:8080")
    try:
        service = client.CoreV1Api().read_namespaced_service(
            name=get_service_name(),
            namespace=get_current_namespace(),
        )
        cluster_ip = (service.spec.cluster_ip or "").strip()
        if cluster_ip and cluster_ip.lower() != "none":
            add(f"{cluster_ip}:8080")
    except ApiException:
        pass
    return hosts


def internal_http_url() -> str:
    return f"http://{get_service_name()}.{get_current_namespace()}:8080"


def is_trino_http_up() -> bool:
    for host in _collect_http_hosts() or [f"{get_service_name()}.{get_current_namespace()}:8080"]:
        url = host if host.startswith("http") else f"http://{host}"
        probe = f"{url.rstrip('/')}/v1/info"
        try:
            with urllib.request.urlopen(probe, timeout=3) as resp:
                if resp.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return False


def wait_for_trino() -> None:
    deadline = time.time() + TRINO_STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if is_trino_http_up():
            return
        time.sleep(10)
    logs = _pod_logs()
    detail = f" Pod status: {_pod_status_summary()}."
    if logs:
        detail += f" Recent logs: {logs.strip().splitlines()[-1]}"
    raise RuntimeError(f"Trino did not become ready within timeout.{detail}")


def _write_solomon_endpoints(info: dict) -> None:
    try:
        from solomon.trino.endpoints_file import write_endpoints

        payload = {
            "internal_http": info.get("internal_http"),
            "http_hosts": info.get("http_hosts") or [],
            "service_name": get_service_name(),
            "catalog": TRINO_CATALOG_NAME,
            "duckdb_file": DUCKDB_FILE,
        }
        path = write_endpoints(payload)
        print(f"Wrote Solomon Trino endpoints to {path}")
    except Exception as exc:
        print(f"Warning: could not write Solomon Trino endpoints file: {exc}")


def get_connection_info() -> dict:
    from solomon.trino.mode import is_internal_trino_mode

    info: dict = {
        "mode": "internal" if is_internal_trino_mode() else "external",
        "deployment_name": get_deployment_name(),
        "service_name": get_service_name(),
        "namespace": get_current_namespace(),
        "trino_image": TRINO_IMAGE,
        "catalog": TRINO_CATALOG_NAME,
        "duckdb_file": DUCKDB_FILE,
        "pod_status": _pod_status_summary(),
        "pod_logs": _pod_logs(tail_lines=80),
        "supervisor_phase": _supervisor_state.get("phase"),
        "supervisor_error": _supervisor_state.get("error"),
    }
    info["http_hosts"] = _collect_http_hosts()
    info["internal_http"] = internal_http_url()
    if is_trino_http_up():
        info["status"] = "running"
        info["message"] = None
    else:
        info["status"] = "starting"
        info["message"] = (
            "Waiting for Trino HTTP on port 8080. "
            f"Pod status: {info['pod_status']}."
        )
    return info


def print_connection_info() -> None:
    info = get_connection_info()
    if info.get("status") == "running":
        _write_solomon_endpoints(info)
    print("\n=== Warehouse (Trino + DuckDB) Connection Info ===")
    print(json.dumps(info, indent=2, sort_keys=True))
    print("==================================================\n")


def run_warehouse_supervisor() -> None:
    from solomon.trino.mode import is_internal_trino_mode

    if not is_internal_trino_mode():
        _supervisor_state["phase"] = "disabled"
        print(
            "Warehouse launcher disabled (TRINO_MODE=external). "
            "Configure CDW / Trino via Site Administration → Data Connections "
            "and TRINO_CONNECTION_NAME on Solomon."
        )
        return

    print("Starting internal warehouse (Trino + DuckDB)...")
    try:
        _supervisor_state["phase"] = "deploying"
        deploy_warehouse()
        _supervisor_state["phase"] = "waiting"
        wait_for_trino()
        _supervisor_state["phase"] = "running"
        print_connection_info()
        while True:
            if not is_trino_http_up():
                print("Trino HTTP is down. Redeploying...")
                _supervisor_state["phase"] = "restarting"
                deploy_warehouse()
                wait_for_trino()
                print_connection_info()
                _supervisor_state["phase"] = "running"
            time.sleep(30)
    except Exception as exc:
        logs = _pod_logs(tail_lines=200)
        print(f"Warehouse supervisor error: {exc}")
        if logs:
            print(f"Latest Trino pod logs:\n{logs[-5000:]}")
        _supervisor_state["phase"] = "error"
        _supervisor_state["error"] = str(exc)
