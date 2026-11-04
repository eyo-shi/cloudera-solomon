"""Kubernetes supervisor for co-located PuppyGraph (internal graph demo mode)."""

from __future__ import annotations

import json
import os
import time

from kubernetes import client, config
from kubernetes.client.rest import ApiException

config.load_incluster_config()

PUPPYGRAPH_IMAGE = os.getenv("PUPPYGRAPH_IMAGE") or "puppygraph/puppygraph:1.15.0"
PUPPYGRAPH_SERVICE_TYPE = os.getenv("PUPPYGRAPH_SERVICE_TYPE") or "ClusterIP"
PUPPYGRAPH_MEMORY = os.getenv("PUPPYGRAPH_MEMORY") or "8Gi"
PUPPYGRAPH_BOLT_PORT = int(os.getenv("PUPPYGRAPH_BOLT_PORT") or "7687")
PUPPYGRAPH_HTTP_PORT = int(os.getenv("PUPPYGRAPH_HTTP_PORT") or "8081")
PUPPYGRAPH_STORAGE_ROOT = os.getenv("PUPPYGRAPH_STORAGE_ROOT") or "/data/storage"
PUPPYGRAPH_STARTUP_TIMEOUT_SECONDS = int(
    os.getenv("PUPPYGRAPH_STARTUP_TIMEOUT_SECONDS") or "1200"
)
PUPPYGRAPH_USERNAME = os.getenv("PUPPYGRAPH_USERNAME") or "puppygraph"
PUPPYGRAPH_PASSWORD = os.getenv("PUPPYGRAPH_PASSWORD") or "puppygraph123"
PUPPYGRAPH_QUERY_TIMEOUT = os.getenv("PUPPYGRAPH_QUERY_TIMEOUT") or "5m"
# The image declares ``USER puppy`` (a name). Under CML's runAsNonRoot policy the
# kubelet rejects non-numeric users with CreateContainerConfigError, so pin the
# numeric IDs (puppy = uid/gid 1000 in /etc/passwd of puppygraph/puppygraph:1.15.0).
PUPPYGRAPH_CONTAINER_UID = int(os.getenv("PUPPYGRAPH_CONTAINER_UID") or "1000")
PUPPYGRAPH_CONTAINER_GID = int(os.getenv("PUPPYGRAPH_CONTAINER_GID") or "1000")

_POD_FAILURE_WAITING_REASONS = (
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "InvalidImageName",
    "RunContainerError",
)

_supervisor_state: dict = {"phase": "initializing", "error": None}
_cached_cluster_ip: str | None = None


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized in ("1", "true", "yes", "on")


PUPPYGRAPH_USE_PVC = _env_bool("PUPPYGRAPH_USE_PVC", default=False)


def get_current_namespace() -> str:
    with open("/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r") as f:
        return f.read().strip()


def get_engine_id() -> str:
    return (os.getenv("CDSW_ENGINE_ID") or "local").strip()


def get_service_name() -> str:
    return f"cml-puppygraph-{get_engine_id()}"


def get_deployment_name() -> str:
    return f"puppygraph-{get_engine_id()}"


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


def _get_project_pvc_claim_name() -> str | None:
    pod_name = (os.getenv("HOSTNAME") or "").strip()
    if not pod_name:
        return None
    try:
        pod = client.CoreV1Api().read_namespaced_pod(
            name=pod_name,
            namespace=get_current_namespace(),
        )
    except ApiException:
        return None
    containers = pod.spec.containers or []
    if not containers:
        return None
    for mount in containers[0].volume_mounts or []:
        if mount.mount_path == "/home/cdsw":
            for vol in pod.spec.volumes or []:
                if vol.name == mount.name and vol.persistent_volume_claim:
                    return vol.persistent_volume_claim.claim_name
    return None


def _puppygraph_container_env() -> list[client.V1EnvVar]:
    return [
        client.V1EnvVar(name="PUPPYGRAPH_USERNAME", value=PUPPYGRAPH_USERNAME),
        client.V1EnvVar(name="PUPPYGRAPH_PASSWORD", value=PUPPYGRAPH_PASSWORD),
        client.V1EnvVar(name="QUERY_TIMEOUT", value=PUPPYGRAPH_QUERY_TIMEOUT),
        client.V1EnvVar(name="STORAGE_PATH_ROOT", value=PUPPYGRAPH_STORAGE_ROOT),
        client.V1EnvVar(name="BOLTSERVER_AUTHENTICATION_ENABLED", value="true"),
    ]


def create_deployment_spec() -> client.V1Deployment:
    namespace = get_current_namespace()
    memory = _normalize_memory(PUPPYGRAPH_MEMORY)
    data_volume = client.V1Volume(name="puppygraph-data")
    pvc_claim = _get_project_pvc_claim_name() if PUPPYGRAPH_USE_PVC else None
    if PUPPYGRAPH_USE_PVC:
        if not pvc_claim:
            raise RuntimeError(
                "PUPPYGRAPH_USE_PVC=true but the launcher pod has no /home/cdsw PVC claim"
            )
        data_volume.persistent_volume_claim = client.V1PersistentVolumeClaimVolumeSource(
            claim_name=pvc_claim
        )
    else:
        data_volume.empty_dir = client.V1EmptyDirVolumeSource()

    data_mount = client.V1VolumeMount(
        name="puppygraph-data",
        mount_path=PUPPYGRAPH_STORAGE_ROOT,
    )
    if PUPPYGRAPH_USE_PVC:
        data_mount.sub_path = "puppygraph-volume"

    puppygraph_container = client.V1Container(
        name="puppygraph",
        image=PUPPYGRAPH_IMAGE,
        image_pull_policy="IfNotPresent",
        ports=[
            client.V1ContainerPort(container_port=PUPPYGRAPH_BOLT_PORT, name="bolt"),
            client.V1ContainerPort(container_port=PUPPYGRAPH_HTTP_PORT, name="http"),
        ],
        env=_puppygraph_container_env(),
        resources=client.V1ResourceRequirements(
            requests={"cpu": "1", "memory": memory},
            limits={"cpu": "4", "memory": memory},
        ),
        startup_probe=client.V1Probe(
            tcp_socket=client.V1TCPSocketAction(port=PUPPYGRAPH_BOLT_PORT),
            period_seconds=15,
            failure_threshold=80,
        ),
        readiness_probe=client.V1Probe(
            tcp_socket=client.V1TCPSocketAction(port=PUPPYGRAPH_BOLT_PORT),
            period_seconds=10,
            failure_threshold=30,
        ),
        volume_mounts=[data_mount],
        security_context=client.V1SecurityContext(
            run_as_user=PUPPYGRAPH_CONTAINER_UID,
            run_as_group=PUPPYGRAPH_CONTAINER_GID,
            run_as_non_root=True,
        ),
    )

    pod_spec = client.V1PodSpec(
        containers=[puppygraph_container],
        volumes=[data_volume],
        security_context=client.V1PodSecurityContext(
            fs_group=PUPPYGRAPH_CONTAINER_GID,
            fs_group_change_policy="Always",
        ),
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
            progress_deadline_seconds=PUPPYGRAPH_STARTUP_TIMEOUT_SECONDS,
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
            type=PUPPYGRAPH_SERVICE_TYPE,
            selector={"app": get_deployment_name()},
            ports=[
                client.V1ServicePort(
                    name="bolt",
                    port=PUPPYGRAPH_BOLT_PORT,
                    target_port=PUPPYGRAPH_BOLT_PORT,
                ),
                client.V1ServicePort(
                    name="http",
                    port=PUPPYGRAPH_HTTP_PORT,
                    target_port=PUPPYGRAPH_HTTP_PORT,
                ),
            ],
        ),
    )


def deploy_puppygraph() -> None:
    _invalidate_cluster_ip_cache()
    apps = client.AppsV1Api()
    core = client.CoreV1Api()
    namespace = get_current_namespace()
    deployment = create_deployment_spec()
    try:
        apps.create_namespaced_deployment(namespace=namespace, body=deployment)
        print(f"Created PuppyGraph deployment {get_deployment_name()}")
    except ApiException as exc:
        if exc.status != 409:
            raise
        apps.replace_namespaced_deployment(
            name=get_deployment_name(),
            namespace=namespace,
            body=deployment,
        )
        print(f"Updated PuppyGraph deployment {get_deployment_name()}")

    service = create_service_spec()
    try:
        core.create_namespaced_service(namespace=namespace, body=service)
        print(f"Created PuppyGraph service {get_service_name()}")
    except ApiException as exc:
        if exc.status != 409:
            raise
        core.replace_namespaced_service(
            name=get_service_name(),
            namespace=namespace,
            body=service,
        )
        print(f"Updated PuppyGraph service {get_service_name()}")
    _print_bolt_endpoint_summary()


def _list_puppygraph_pods() -> list[client.V1Pod]:
    core = client.CoreV1Api()
    pods = core.list_namespaced_pod(
        namespace=get_current_namespace(),
        label_selector=f"app={get_deployment_name()}",
    )
    return pods.items or []


def _format_container_status(name: str, status: client.V1ContainerStatus) -> str:
    state = status.state
    if state.waiting:
        waiting = state.waiting
        detail = waiting.message or waiting.reason or "waiting"
        return f"{name}: waiting ({waiting.reason or 'Unknown'}) {detail}"
    if state.terminated:
        terminated = state.terminated
        return (
            f"{name}: terminated reason={terminated.reason} "
            f"exit={terminated.exit_code} message={terminated.message or ''}"
        )
    if state.running:
        return f"{name}: running"
    return f"{name}: unknown"


def _describe_pod(pod: client.V1Pod) -> str:
    parts = [f"{pod.metadata.name}: phase={pod.status.phase}"]
    for status in pod.status.container_statuses or []:
        parts.append(_format_container_status(status.name, status))
    return " | ".join(parts)


def _pod_status_summary() -> str | None:
    pods = _list_puppygraph_pods()
    if not pods:
        return "no pod"
    return _describe_pod(pods[0])


def _pod_logs(tail_lines: int = 120) -> str | None:
    pods = _list_puppygraph_pods()
    if not pods:
        return None
    try:
        return client.CoreV1Api().read_namespaced_pod_log(
            name=pods[0].metadata.name,
            namespace=get_current_namespace(),
            tail_lines=tail_lines,
            container="puppygraph",
        )
    except ApiException:
        return None


def _pod_has_fatal_failure() -> bool:
    for pod in _list_puppygraph_pods():
        for status in pod.status.container_statuses or []:
            waiting = status.state.waiting
            if waiting and waiting.reason in _POD_FAILURE_WAITING_REASONS:
                return True
    return False


def _invalidate_cluster_ip_cache() -> None:
    global _cached_cluster_ip
    _cached_cluster_ip = None


def _get_service_cluster_ip(*, warn: bool = False) -> str | None:
    global _cached_cluster_ip
    if _cached_cluster_ip:
        return _cached_cluster_ip
    try:
        service = client.CoreV1Api().read_namespaced_service(
            name=get_service_name(),
            namespace=get_current_namespace(),
        )
        cluster_ip = (service.spec.cluster_ip or "").strip()
        if cluster_ip and cluster_ip.lower() != "none":
            _cached_cluster_ip = cluster_ip
            return cluster_ip
    except ApiException as exc:
        if warn and exc.status != 404:
            print(
                f"Warning: could not read PuppyGraph service ClusterIP "
                f"({get_service_name()}): {exc.reason}"
            )
    return None


def _pod_bolt_hosts() -> list[str]:
    hosts: list[str] = []
    for pod in _list_puppygraph_pods():
        if pod.status.pod_ip:
            hosts.append(f"{pod.status.pod_ip}:{PUPPYGRAPH_BOLT_PORT}")
    return hosts


def internal_bolt_uri() -> str:
    return (
        f"bolt://{get_service_name()}.{get_current_namespace()}:{PUPPYGRAPH_BOLT_PORT}"
    )


def internal_http_url() -> str:
    return f"http://{get_service_name()}.{get_current_namespace()}:{PUPPYGRAPH_HTTP_PORT}"


def _collect_bolt_hosts() -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()

    def add(host: str | None) -> None:
        text = (host or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        hosts.append(text)

    cluster_ip = _get_service_cluster_ip()
    if cluster_ip:
        add(f"{cluster_ip}:{PUPPYGRAPH_BOLT_PORT}")
    internal = internal_bolt_uri()
    if internal.startswith("bolt://"):
        host_part = internal.removeprefix("bolt://")
        add(host_part)
    for host in _pod_bolt_hosts():
        add(host)
    return hosts


def _launcher_bolt_probe_uris() -> list[str]:
    uris: list[str] = []
    seen: set[str] = set()

    def add(uri: str | None) -> None:
        text = (uri or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        uris.append(text)

    add(internal_bolt_uri())
    cluster_ip = _get_service_cluster_ip()
    if cluster_ip:
        add(f"bolt://{cluster_ip}:{PUPPYGRAPH_BOLT_PORT}")
    for host in _pod_bolt_hosts():
        add(f"bolt://{host}")
    return uris


def _probe_bolt_uris(uris: list[str]) -> tuple[bool, str | None]:
    from solomon.graph.bolt_probe import probe_bolt

    last_error: str | None = None
    for uri in uris:
        ok, last_error = probe_bolt(
            uri,
            username=PUPPYGRAPH_USERNAME,
            password=PUPPYGRAPH_PASSWORD,
            timeout=5.0,
        )
        if ok:
            return True, None
    return False, last_error


def is_puppygraph_bolt_up() -> bool:
    ok, _ = _probe_bolt_uris(_launcher_bolt_probe_uris())
    return ok


def wait_for_puppygraph() -> None:
    deadline = time.time() + PUPPYGRAPH_STARTUP_TIMEOUT_SECONDS
    next_status_log = time.time()
    last_probe_error: str | None = None
    while time.time() < deadline:
        ok, last_probe_error = _probe_bolt_uris(_launcher_bolt_probe_uris())
        if ok:
            _write_solomon_endpoints(get_connection_info())
            return
        if time.time() >= next_status_log:
            print(
                "Waiting for PuppyGraph Bolt on port "
                f"{PUPPYGRAPH_BOLT_PORT}. Pod status: {_pod_status_summary()}."
            )
            if last_probe_error:
                print(f"Latest Bolt probe: {last_probe_error}")
            next_status_log = time.time() + 60
        if _pod_has_fatal_failure():
            logs = _pod_logs()
            detail = f" Pod status: {_pod_status_summary()}."
            if logs:
                detail += f"\nRecent pod logs:\n{logs[-3000:]}"
            raise RuntimeError(
                "PuppyGraph pod failed during startup (see diagnostics below).\n"
                + detail
            )
        time.sleep(10)
    logs = _pod_logs()
    detail = f" Pod status: {_pod_status_summary()}."
    if logs:
        detail += f"\nRecent pod logs:\n{logs[-3000:]}"
    raise RuntimeError(f"PuppyGraph did not become ready within timeout.\n{detail}")


def _write_solomon_endpoints(info: dict) -> None:
    try:
        from solomon.graph.puppygraph_endpoints_file import write_endpoints

        bolt_uri = info.get("internal_bolt") or internal_bolt_uri()
        payload = {
            "internal_bolt": bolt_uri,
            "bolt_uri": bolt_uri,
            "bolt_hosts": info.get("bolt_hosts") or [],
            "service_name": get_service_name(),
            "namespace": get_current_namespace(),
            "web_ui_http": info.get("internal_http"),
        }
        path = write_endpoints(payload)
        print(f"Wrote Solomon PuppyGraph endpoints to {path}")
        hosts = payload["bolt_hosts"]
        if hosts:
            print(
                "Solomon PUPPYGRAPH_URI (if DNS fails): "
                f"bolt://{hosts[0]}"
            )
    except Exception as exc:
        print(f"Warning: could not write Solomon PuppyGraph endpoints file: {exc}")


def get_connection_info() -> dict:
    from solomon.graph.puppygraph_mode import is_internal_puppygraph_mode

    info: dict = {
        "mode": "internal" if is_internal_puppygraph_mode() else "external",
        "deployment_name": get_deployment_name(),
        "service_name": get_service_name(),
        "namespace": get_current_namespace(),
        "puppygraph_image": PUPPYGRAPH_IMAGE,
        "bolt_port": PUPPYGRAPH_BOLT_PORT,
        "http_port": PUPPYGRAPH_HTTP_PORT,
        "pod_status": _pod_status_summary(),
        "pod_logs": _pod_logs(tail_lines=80),
        "supervisor_phase": _supervisor_state.get("phase"),
        "supervisor_error": _supervisor_state.get("error"),
        "cluster_ip": _get_service_cluster_ip(),
    }
    info["bolt_hosts"] = _collect_bolt_hosts()
    info["internal_bolt"] = internal_bolt_uri()
    info["internal_http"] = internal_http_url()
    info["launcher_probe_uris"] = _launcher_bolt_probe_uris()
    if is_puppygraph_bolt_up():
        info["status"] = "running"
        info["message"] = None
    else:
        info["status"] = "starting"
        info["message"] = (
            f"Waiting for PuppyGraph Bolt on port {PUPPYGRAPH_BOLT_PORT}. "
            f"Pod status: {info['pod_status']}."
        )
    return info


def _print_bolt_endpoint_summary() -> None:
    cluster_ip = _get_service_cluster_ip()
    internal = internal_bolt_uri()
    print("=== PuppyGraph Bolt endpoints ===")
    print(f"Solomon internal Bolt (preferred): {internal}")
    if cluster_ip:
        print(
            "Solomon PUPPYGRAPH_URI (Service ClusterIP, if DNS fails): "
            f"bolt://{cluster_ip}:{PUPPYGRAPH_BOLT_PORT}"
        )
    print(f"PuppyGraph Web UI (in-cluster): {internal_http_url()}")
    print("=================================")


def print_connection_info() -> None:
    info = get_connection_info()
    if info.get("status") == "running":
        _write_solomon_endpoints(info)
    print("\n=== PuppyGraph Connection Info ===")
    print(json.dumps(info, indent=2, sort_keys=True))
    print("==================================\n")


def run_puppygraph_supervisor() -> None:
    from solomon.graph.puppygraph_mode import is_internal_puppygraph_mode

    if not is_internal_puppygraph_mode():
        _supervisor_state["phase"] = "disabled"
        print(
            "PuppyGraph launcher disabled (PUPPYGRAPH_MODE=external). "
            "Configure external PuppyGraph via PUPPYGRAPH_URI in .solomon/deploy.env "
            "on Solomon Application."
        )
        return

    print("Starting internal PuppyGraph (Bolt + Web UI)...")
    try:
        _supervisor_state["phase"] = "deploying"
        deploy_puppygraph()
        _print_bolt_endpoint_summary()
        _supervisor_state["phase"] = "waiting"
        wait_for_puppygraph()
        _supervisor_state["phase"] = "running"
        print_connection_info()
        while True:
            if not is_puppygraph_bolt_up():
                print("PuppyGraph Bolt is down. Redeploying...")
                _supervisor_state["phase"] = "restarting"
                deploy_puppygraph()
                wait_for_puppygraph()
                print_connection_info()
                _supervisor_state["phase"] = "running"
            time.sleep(30)
    except Exception as exc:
        logs = _pod_logs(tail_lines=200)
        print(f"PuppyGraph supervisor error: {exc}")
        if logs:
            print(f"Latest PuppyGraph pod logs:\n{logs[-5000:]}")
        _supervisor_state["phase"] = "error"
        _supervisor_state["error"] = str(exc)
