"""Kubernetes supervisor for co-located OpenSearch (CML demo mode)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from kubernetes import client, config
from kubernetes.client.rest import ApiException

config.load_incluster_config()

OPENSEARCH_IMAGE = os.getenv("OPENSEARCH_IMAGE") or "opensearchproject/opensearch:2.11.1"
OPENSEARCH_DASHBOARDS_IMAGE = (
    os.getenv("OPENSEARCH_DASHBOARDS_IMAGE")
    or "opensearchproject/opensearch-dashboards:2.11.1"
)
OPENSEARCH_SERVICE_TYPE = os.getenv("OPENSEARCH_SERVICE_TYPE") or "ClusterIP"
OPENSEARCH_MEMORY = os.getenv("OPENSEARCH_MEMORY") or "2Gi"
OPENSEARCH_DASHBOARDS_MEMORY = os.getenv("OPENSEARCH_DASHBOARDS_MEMORY") or "1Gi"
OPENSEARCH_JAVA_OPTS = os.getenv("OPENSEARCH_JAVA_OPTS") or "-Xms512m -Xmx512m"
DASHBOARDS_BASE_PATH = "/dashboards"
DASHBOARDS_HOME_PATH = f"{DASHBOARDS_BASE_PATH}/app/home"
OPENSEARCH_STARTUP_TIMEOUT_SECONDS = int(
    os.getenv("OPENSEARCH_STARTUP_TIMEOUT_SECONDS") or "900"
)
OPENSEARCH_CONTAINER_UID = 1000
OPENSEARCH_CONTAINER_GID = 1000

_supervisor_state: dict = {"phase": "initializing", "error": None}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized in ("1", "true", "yes", "on")


OPENSEARCH_USE_PVC = _env_bool("OPENSEARCH_USE_PVC", default=False)


def get_current_namespace() -> str:
    with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r") as f:
        return f.read().strip()


def get_engine_id() -> str:
    return (os.getenv("CDSW_ENGINE_ID") or "local").strip()


def get_service_name() -> str:
    return f"cml-opensearch-{get_engine_id()}"


def get_deployment_name() -> str:
    return f"opensearch-{get_engine_id()}"


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


def _opensearch_container_env() -> list[client.V1EnvVar]:
    return [
        client.V1EnvVar(name="discovery.type", value="single-node"),
        client.V1EnvVar(name="plugins.security.disabled", value="true"),
        client.V1EnvVar(name="DISABLE_INSTALL_DEMO_CONFIG", value="true"),
        client.V1EnvVar(name="OPENSEARCH_JAVA_OPTS", value=OPENSEARCH_JAVA_OPTS),
        client.V1EnvVar(name="bootstrap.memory_lock", value="false"),
    ]


def _dashboards_container_env() -> list[client.V1EnvVar]:
    return [
        client.V1EnvVar(name="OPENSEARCH_HOSTS", value='["http://127.0.0.1:9200"]'),
        client.V1EnvVar(name="DISABLE_SECURITY_DASHBOARDS_PLUGIN", value="true"),
        client.V1EnvVar(name="SERVER_HOST", value="0.0.0.0"),
        client.V1EnvVar(name="SERVER_PORT", value="5601"),
        client.V1EnvVar(name="SERVER_BASEPATH", value=DASHBOARDS_BASE_PATH),
        client.V1EnvVar(name="SERVER_REWRITEBASEPATH", value="true"),
    ]


def create_deployment_spec() -> client.V1Deployment:
    namespace = get_current_namespace()
    memory = _normalize_memory(OPENSEARCH_MEMORY)
    dashboards_memory = _normalize_memory(OPENSEARCH_DASHBOARDS_MEMORY)
    data_volume = client.V1Volume(name="opensearch-data")
    if OPENSEARCH_USE_PVC:
        pod_name = (os.getenv("HOSTNAME") or "").strip()
        pod_spec = client.CoreV1Api().read_namespaced_pod(
            name=pod_name,
            namespace=namespace,
        )
        claim_name = None
        for mount in pod_spec.spec.containers[0].volume_mounts or []:
            if mount.mount_path == "/home/cdsw":
                for volume in pod_spec.spec.volumes or []:
                    if volume.name == mount.name and volume.persistent_volume_claim:
                        claim_name = volume.persistent_volume_claim.claim_name
                        break
        if not claim_name:
            raise RuntimeError("PVC claim for /home/cdsw not found")
        data_volume.persistent_volume_claim = client.V1PersistentVolumeClaimVolumeSource(
            claim_name=claim_name
        )
    else:
        data_volume.empty_dir = client.V1EmptyDirVolumeSource()

    data_mount = client.V1VolumeMount(name="opensearch-data", mount_path="/usr/share/opensearch/data")
    if OPENSEARCH_USE_PVC:
        data_mount.sub_path = "opensearch-volume"

    pod_spec = client.V1PodSpec(
        security_context=client.V1PodSecurityContext(
            fs_group=OPENSEARCH_CONTAINER_GID,
            fs_group_change_policy="Always",
        ),
        containers=[
            client.V1Container(
                name="opensearch",
                image=OPENSEARCH_IMAGE,
                image_pull_policy="IfNotPresent",
                security_context=client.V1SecurityContext(
                    run_as_user=OPENSEARCH_CONTAINER_UID,
                    run_as_group=OPENSEARCH_CONTAINER_GID,
                ),
                ports=[client.V1ContainerPort(container_port=9200, name="http")],
                env=_opensearch_container_env(),
                resources=client.V1ResourceRequirements(
                    requests={"cpu": "500m", "memory": memory},
                    limits={"cpu": "2", "memory": memory},
                ),
                startup_probe=client.V1Probe(
                    http_get=client.V1HTTPGetAction(path="/", port=9200),
                    period_seconds=10,
                    failure_threshold=60,
                ),
                readiness_probe=client.V1Probe(
                    http_get=client.V1HTTPGetAction(path="/", port=9200),
                    period_seconds=10,
                    failure_threshold=30,
                ),
                volume_mounts=[data_mount],
            ),
            client.V1Container(
                name="opensearch-dashboards",
                image=OPENSEARCH_DASHBOARDS_IMAGE,
                image_pull_policy="IfNotPresent",
                security_context=client.V1SecurityContext(
                    run_as_user=OPENSEARCH_CONTAINER_UID,
                    run_as_group=OPENSEARCH_CONTAINER_GID,
                ),
                ports=[client.V1ContainerPort(container_port=5601, name="dashboards")],
                env=_dashboards_container_env(),
                resources=client.V1ResourceRequirements(
                    requests={"cpu": "250m", "memory": dashboards_memory},
                    limits={"cpu": "1", "memory": dashboards_memory},
                ),
                startup_probe=client.V1Probe(
                    http_get=client.V1HTTPGetAction(
                        path=f"{DASHBOARDS_BASE_PATH}/api/status",
                        port=5601,
                    ),
                    period_seconds=10,
                    failure_threshold=60,
                ),
                readiness_probe=client.V1Probe(
                    http_get=client.V1HTTPGetAction(
                        path=f"{DASHBOARDS_BASE_PATH}/api/status",
                        port=5601,
                    ),
                    period_seconds=10,
                    failure_threshold=30,
                ),
            ),
        ],
        volumes=[data_volume],
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
            progress_deadline_seconds=600,
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
            type=OPENSEARCH_SERVICE_TYPE,
            selector={"app": get_deployment_name()},
            ports=[
                client.V1ServicePort(name="http", port=9200, target_port=9200),
                client.V1ServicePort(name="dashboards", port=5601, target_port=5601),
            ],
        ),
    )


def deploy_opensearch() -> None:
    apps = client.AppsV1Api()
    core = client.CoreV1Api()
    namespace = get_current_namespace()
    deployment = create_deployment_spec()
    try:
        apps.create_namespaced_deployment(namespace=namespace, body=deployment)
        print(f"Created OpenSearch deployment {get_deployment_name()}")
    except ApiException as exc:
        if exc.status != 409:
            raise
        apps.replace_namespaced_deployment(
            name=get_deployment_name(),
            namespace=namespace,
            body=deployment,
        )
        print(f"Updated OpenSearch deployment {get_deployment_name()}")

    service = create_service_spec()
    try:
        core.create_namespaced_service(namespace=namespace, body=service)
        print(f"Created OpenSearch service {get_service_name()}")
    except ApiException as exc:
        if exc.status != 409:
            raise
        core.replace_namespaced_service(
            name=get_service_name(),
            namespace=namespace,
            body=service,
        )
        print(f"Updated OpenSearch service {get_service_name()}")


def _list_opensearch_pods() -> list[client.V1Pod]:
    core = client.CoreV1Api()
    pods = core.list_namespaced_pod(
        namespace=get_current_namespace(),
        label_selector=f"app={get_deployment_name()}",
    )
    return pods.items or []


def _pod_status_summary() -> str | None:
    pods = _list_opensearch_pods()
    if not pods:
        return "no pod"
    pod = pods[0]
    phase = pod.status.phase or "Unknown"
    if pod.status.container_statuses:
        waiting = pod.status.container_statuses[0].state.waiting
        if waiting and waiting.reason:
            return f"{phase}/{waiting.reason}"
    return phase


def _pod_logs(tail_lines: int = 120) -> str | None:
    pods = _list_opensearch_pods()
    if not pods:
        return None
    try:
        return client.CoreV1Api().read_namespaced_pod_log(
            name=pods[0].metadata.name,
            namespace=get_current_namespace(),
            tail_lines=tail_lines,
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

    for pod in _list_opensearch_pods():
        if pod.status.pod_ip:
            add(f"{pod.status.pod_ip}:9200")
    try:
        service = client.CoreV1Api().read_namespaced_service(
            name=get_service_name(),
            namespace=get_current_namespace(),
        )
        cluster_ip = (service.spec.cluster_ip or "").strip()
        if cluster_ip and cluster_ip.lower() != "none":
            add(f"{cluster_ip}:9200")
    except ApiException:
        pass
    return hosts


def internal_http_url() -> str:
    return f"http://{get_service_name()}.{get_current_namespace()}:9200"


def internal_dashboards_url() -> str:
    return f"http://{get_service_name()}.{get_current_namespace()}:5601"


def build_proxied_dashboards_path() -> str:
    """Public path (via CML Application URL) for OpenSearch Dashboards."""
    return DASHBOARDS_HOME_PATH


def _http_probe(url: str) -> bool:
    if not url.endswith("/"):
        probe_url = url
    else:
        probe_url = url
    try:
        with urllib.request.urlopen(probe_url, timeout=3) as resp:
            return resp.status < 500
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def is_dashboards_http_up() -> bool:
    status_url = f"{internal_dashboards_url()}{DASHBOARDS_BASE_PATH}/api/status"
    return _http_probe(status_url)


def is_opensearch_http_up() -> bool:
    for host in _collect_http_hosts() or [f"{get_service_name()}.{get_current_namespace()}"]:
        url = host if host.startswith("http") else f"http://{host}"
        if not url.endswith("/"):
            url = f"{url}/"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return False


def wait_for_opensearch() -> None:
    deadline = time.time() + OPENSEARCH_STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if is_opensearch_http_up():
            return
        time.sleep(10)
    logs = _pod_logs()
    detail = f" Pod status: {_pod_status_summary()}."
    if logs:
        detail += f" Recent logs: {logs.strip().splitlines()[-1]}"
    raise RuntimeError(f"OpenSearch did not become ready within timeout.{detail}")


def wait_for_dashboards() -> None:
    deadline = time.time() + OPENSEARCH_STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if is_dashboards_http_up():
            return
        time.sleep(10)
    logs = _pod_logs()
    detail = f" Pod status: {_pod_status_summary()}."
    if logs:
        detail += f" Recent logs: {logs.strip().splitlines()[-1]}"
    raise RuntimeError(
        "OpenSearch Dashboards did not become ready within timeout." + detail
    )


def _write_solomon_endpoints(info: dict) -> None:
    try:
        from solomon.opensearch.endpoints_file import write_endpoints

        payload = {
            "internal_http": info.get("internal_http"),
            "http_hosts": info.get("http_hosts") or [],
            "service_name": get_service_name(),
            "namespace": get_current_namespace(),
        }
        path = write_endpoints(payload)
        print(f"Solomon endpoints file: {path}")
        hosts = payload["http_hosts"]
        if hosts:
            print(
                "Solomon OPENSEARCH_ENDPOINT (if DNS fails): "
                f"http://{hosts[0]}"
            )
    except Exception as exc:
        print(f"Warning: could not write Solomon OpenSearch endpoints file: {exc}")


def get_connection_info() -> dict:
    info = {
        "status": "starting",
        "internal_http": internal_http_url(),
        "internal_dashboards": internal_dashboards_url(),
        "proxied_dashboards_path": build_proxied_dashboards_path(),
        "http_hosts": _collect_http_hosts(),
        "service_name": get_service_name(),
        "namespace": get_current_namespace(),
        "pod_status": _pod_status_summary(),
        "pod_logs": _pod_logs(),
        "supervisor_phase": _supervisor_state.get("phase"),
        "supervisor_error": _supervisor_state.get("error"),
        "dashboards_ready": is_dashboards_http_up(),
    }
    if is_opensearch_http_up() and info["dashboards_ready"]:
        info["status"] = "running"
        info["message"] = None
    elif is_opensearch_http_up():
        info["message"] = (
            "OpenSearch is up; waiting for OpenSearch Dashboards on port 5601. "
            f"Pod status: {info['pod_status']}."
        )
    else:
        info["message"] = (
            "Waiting for OpenSearch HTTP endpoint on port 9200. "
            f"Pod status: {info['pod_status']}."
        )
    return info


def _bootstrap_search_index() -> None:
    try:
        from solomon.opensearch.bootstrap import bootstrap_search_index

        if bootstrap_search_index():
            print("OpenSearch search index is ready.")
        else:
            print(
                "OpenSearch search index bootstrap skipped "
                "(Solomon will retry on Application startup)."
            )
    except Exception as exc:
        print(f"Warning: OpenSearch search index bootstrap failed: {exc}")


def print_connection_info() -> None:
    info = get_connection_info()
    if info.get("status") == "running":
        _write_solomon_endpoints(info)
        _bootstrap_search_index()
    print("\n=== OpenSearch Connection Info ===")
    print(json.dumps(info, indent=2, sort_keys=True))
    print("==================================\n")


def run_opensearch_supervisor() -> None:
    from solomon.opensearch.mode import is_internal_opensearch_mode

    if not is_internal_opensearch_mode():
        _supervisor_state["phase"] = "disabled"
        print(
            "OpenSearch launcher disabled (OPENSEARCH_MODE=external). "
            "Configure external OpenSearch via Project Settings > Advanced > "
            "Environment Variables (OPENSEARCH_CONNECTION_NAME or "
            "OPENSEARCH_ENDPOINT) on Solomon."
        )
        return

    print("Starting OpenSearch server (internal mode)...")
    try:
        _supervisor_state["phase"] = "deploying"
        deploy_opensearch()
        _supervisor_state["phase"] = "waiting"
        wait_for_opensearch()
        wait_for_dashboards()
        _supervisor_state["phase"] = "running"
        print_connection_info()
        while True:
            if not is_opensearch_http_up() or not is_dashboards_http_up():
                print("OpenSearch HTTP is down. Redeploying...")
                _supervisor_state["phase"] = "restarting"
                deploy_opensearch()
                wait_for_opensearch()
                wait_for_dashboards()
                print_connection_info()
                _supervisor_state["phase"] = "running"
            time.sleep(30)
    except Exception as exc:
        logs = _pod_logs(tail_lines=200)
        print(f"OpenSearch supervisor error: {exc}")
        if logs:
            print(f"Latest OpenSearch pod logs:\n{logs[-5000:]}")
        _supervisor_state["phase"] = "error"
        _supervisor_state["error"] = str(exc)
