"""Kubernetes supervisor for co-located Trino + DuckDB (internal warehouse demo mode)."""

from __future__ import annotations

import base64
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
DUCKDB_INIT_IMAGE = os.getenv("DUCKDB_INIT_IMAGE") or "busybox:1.36"
DUCKDB_FILE = os.getenv("DUCKDB_FILE") or "/data/solomon/solomon.duckdb"
TRINO_STARTUP_TIMEOUT_SECONDS = int(os.getenv("TRINO_STARTUP_TIMEOUT_SECONDS") or "900")
TRINO_CATALOG_NAME = os.getenv("TRINO_CATALOG_NAME") or "iceberg"
TRINO_CONTAINER_UID = int(os.getenv("TRINO_CONTAINER_UID") or "1000")
TRINO_CONTAINER_GID = int(os.getenv("TRINO_CONTAINER_GID") or "1000")
_SOLOMON_DUCKDB_REL = Path(".solomon") / "solomon.duckdb"
_POD_FAILURE_WAITING_REASONS = (
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "InvalidImageName",
    "RunContainerError",
    "Init:CrashLoopBackOff",
    "Init:Error",
)

_supervisor_state: dict = {"phase": "initializing", "error": None}
_deploy_ctx: dict = {
    "use_pvc": False,
    "pvc_claim": None,
    "duckdb_file": DUCKDB_FILE,
}
_cached_cluster_ip: str | None = None


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


def _duckdb_project_path() -> Path:
    for key in ("CDSW_PROJECT_DIR", "CML_PROJECT_DIR"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return Path(raw) / _SOLOMON_DUCKDB_REL
    # CML sessions usually cwd=/home/cdsw even when CDSW_PROJECT_DIR is unset.
    if Path("/home/cdsw").is_dir():
        return Path("/home/cdsw") / _SOLOMON_DUCKDB_REL
    return Path.cwd() / _SOLOMON_DUCKDB_REL


def _ensure_duckdb_seeded() -> Path:
    from solomon.trino.duckdb_seed import seed_duckdb_database

    path = _duckdb_project_path()
    seeded = seed_duckdb_database(path)
    if path.is_file():
        path.chmod(0o664)
    print(
        f"Seeded DuckDB database at {path}"
        if seeded
        else f"DuckDB database already present at {path}"
    )
    return path


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


def _use_project_pvc(pvc_claim: str | None) -> bool:
    if pvc_claim is None:
        return False
    # emptyDir + ConfigMap binary fallback is capped at 1 MiB; prefer project PVC.
    if _env_bool("TRINO_FORCE_EMPTYDIR", default=False):
        return False
    return True


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
    duckdb_file = str(_deploy_ctx.get("duckdb_file") or DUCKDB_FILE)
    return "\n".join(
        [
            "connector.name=duckdb",
            f"connection-url=jdbc:duckdb:{duckdb_file}",
            "",
        ]
    )


def ensure_configmaps(
    *,
    include_duckdb_binary: bool = False,
    duckdb_path: Path | None = None,
) -> None:
    core = client.CoreV1Api()
    namespace = get_current_namespace()
    binary_data = None
    if include_duckdb_binary:
        if duckdb_path is None or not duckdb_path.is_file():
            raise RuntimeError(
                f"DuckDB seed file is required for emptyDir mode: {duckdb_path}"
            )
        duckdb_bytes = duckdb_path.read_bytes()
        # ConfigMap total size limit is 1 MiB (base64 adds ~33% overhead).
        if len(duckdb_bytes) > 700_000:
            raise RuntimeError(
                f"DuckDB file {duckdb_path} is {len(duckdb_bytes)} bytes — too large "
                "for ConfigMap emptyDir mode. Mount the project PVC (/home/cdsw) "
                "or set TRINO_FORCE_EMPTYDIR=false (default)."
            )
        binary_data = {
            "solomon.duckdb": base64.b64encode(duckdb_bytes).decode("ascii")
        }
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
        },
        binary_data=binary_data,
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


def _data_volume(*, use_pvc: bool, pvc_claim: str) -> client.V1Volume:
    volume = client.V1Volume(name="warehouse-data")
    if use_pvc:
        volume.persistent_volume_claim = client.V1PersistentVolumeClaimVolumeSource(
            claim_name=pvc_claim
        )
    else:
        volume.empty_dir = client.V1EmptyDirVolumeSource()
    return volume


def _trino_container_security_context() -> client.V1SecurityContext:
    """trinodb/trino runs as user ``trino`` (uid 1000); CML requires numeric IDs."""
    return client.V1SecurityContext(
        run_as_user=TRINO_CONTAINER_UID,
        run_as_group=TRINO_CONTAINER_GID,
        run_as_non_root=True,
    )


def _data_mount(*, use_pvc: bool) -> client.V1VolumeMount:
    duckdb_file = str(_deploy_ctx.get("duckdb_file") or DUCKDB_FILE)
    if use_pvc:
        return client.V1VolumeMount(
            name="warehouse-data",
            mount_path=str(Path(duckdb_file).parent),
            sub_path=str(_SOLOMON_DUCKDB_REL.parent),
        )
    return client.V1VolumeMount(name="warehouse-data", mount_path="/data")


def create_deployment_spec() -> client.V1Deployment:
    namespace = get_current_namespace()
    memory = _normalize_memory(TRINO_MEMORY)
    use_pvc = bool(_deploy_ctx.get("use_pvc"))
    pvc_claim = str(_deploy_ctx.get("pvc_claim") or "")
    duckdb_file = str(_deploy_ctx.get("duckdb_file") or DUCKDB_FILE)
    data_volume = _data_volume(use_pvc=use_pvc, pvc_claim=pvc_claim)
    data_mount = _data_mount(use_pvc=use_pvc)

    config_volume = client.V1Volume(
        name="warehouse-config",
        config_map=client.V1ConfigMapVolumeSource(name=get_configmap_name()),
    )

    init_containers: list[client.V1Container] = []
    if not use_pvc:
        init_containers.append(
            client.V1Container(
                name="duckdb-init",
                image=DUCKDB_INIT_IMAGE,
                image_pull_policy="IfNotPresent",
                security_context=_trino_container_security_context(),
                command=["sh", "-c"],
                args=[
                    f"mkdir -p $(dirname {duckdb_file}) && "
                    f"cp /config/solomon.duckdb {duckdb_file}"
                ],
                volume_mounts=[
                    data_mount,
                    client.V1VolumeMount(
                        name="warehouse-config", mount_path="/config"
                    ),
                ],
            )
        )

    trino_container = client.V1Container(
        name="trino",
        image=TRINO_IMAGE,
        image_pull_policy="IfNotPresent",
        security_context=_trino_container_security_context(),
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
        security_context=client.V1PodSecurityContext(
            fs_group=TRINO_CONTAINER_GID,
            fs_group_change_policy="Always",
        ),
        init_containers=init_containers,
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
    _invalidate_cluster_ip_cache()
    duckdb_path = _ensure_duckdb_seeded()
    pvc_claim = _get_project_pvc_claim_name()
    use_pvc = _use_project_pvc(pvc_claim)
    if TRINO_USE_PVC and not pvc_claim:
        raise RuntimeError(
            "TRINO_USE_PVC=true but the launcher pod has no /home/cdsw PVC claim"
        )
    _deploy_ctx.update(
        use_pvc=use_pvc,
        pvc_claim=pvc_claim,
        duckdb_file=DUCKDB_FILE,
    )
    print(
        "Warehouse DuckDB storage: "
        f"path={duckdb_path}, trino_file={DUCKDB_FILE}, "
        f"use_pvc={use_pvc}, pvc_claim={pvc_claim or 'none'}"
    )
    ensure_configmaps(
        include_duckdb_binary=not use_pvc,
        duckdb_path=duckdb_path,
    )
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
    cluster_ip = _get_service_cluster_ip()
    if cluster_ip:
        print(
            f"Warehouse Trino Service ClusterIP: http://{cluster_ip}:8080 "
            "(Kubernetes-assigned; use for Solomon TRINO_ENDPOINT if DNS fails)"
        )
    print(f"Warehouse Trino internal DNS: {internal_http_url()}")


def _list_warehouse_pods() -> list[client.V1Pod]:
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
    for status in pod.status.init_container_statuses or []:
        parts.append(_format_container_status(status.name, status))
    for status in pod.status.container_statuses or []:
        parts.append(_format_container_status(status.name, status))
    return " | ".join(parts)


def _get_k8s_events(limit: int = 12) -> str | None:
    deployment_name = get_deployment_name()
    lines: list[str] = []
    try:
        events = client.CoreV1Api().list_namespaced_event(
            namespace=get_current_namespace(),
        )
        relevant = [
            event
            for event in events.items
            if deployment_name in (event.involved_object.name or "")
        ]
        for event in sorted(
            relevant,
            key=lambda item: item.last_timestamp or item.event_time,
        )[-limit:]:
            involved = event.involved_object
            lines.append(
                f"{event.type} {event.reason} "
                f"[{involved.kind}/{involved.name}]: {event.message}"
            )
        return "\n".join(lines) if lines else None
    except ApiException:
        return None


def _pod_has_fatal_failure() -> bool:
    for pod in _list_warehouse_pods():
        for status in pod.status.init_container_statuses or []:
            waiting = status.state.waiting
            if waiting and waiting.reason in _POD_FAILURE_WAITING_REASONS:
                return True
        for status in pod.status.container_statuses or []:
            waiting = status.state.waiting
            if waiting and waiting.reason in _POD_FAILURE_WAITING_REASONS:
                return True
    return False


def _pod_diagnostics_text() -> str:
    pods = _list_warehouse_pods()
    parts: list[str] = []
    if pods:
        parts.append("Pods: " + " | ".join(_describe_pod(pod) for pod in pods))
    events = _get_k8s_events()
    if events:
        parts.append("K8s events:\n" + events)
    return "\n".join(parts)


def _pod_status_summary() -> str | None:
    pods = _list_warehouse_pods()
    if not pods:
        return "no pod"
    return _describe_pod(pods[0])


def _pod_logs(tail_lines: int = 120) -> str | None:
    pods = _list_warehouse_pods()
    if not pods:
        return None
    pod_name = pods[0].metadata.name
    namespace = get_current_namespace()
    core = client.CoreV1Api()
    for container in ("trino", "duckdb-init"):
        try:
            return core.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=tail_lines,
                container=container,
            )
        except ApiException:
            continue
    return None


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
                f"Warning: could not read Trino service ClusterIP "
                f"({get_service_name()}): {exc.reason}"
            )
    return None


def _pod_http_hosts() -> list[str]:
    hosts: list[str] = []
    for pod in _list_warehouse_pods():
        if pod.status.pod_ip:
            hosts.append(f"{pod.status.pod_ip}:8080")
    return hosts


def _collect_http_hosts() -> list[str]:
    """Return host:port strings for Solomon; Service ClusterIP first when known."""
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
        add(f"{cluster_ip}:8080")
    internal = internal_http_url()
    from urllib.parse import urlparse

    parsed = urlparse(internal)
    if parsed.hostname:
        port = parsed.port or 8080
        add(f"{parsed.hostname}:{port}")
    for host in _pod_http_hosts():
        add(host)
    return hosts


def internal_http_url() -> str:
    return f"http://{get_service_name()}.{get_current_namespace()}:8080"


def _launcher_http_probe_urls() -> list[str]:
    """Probe order for warehouse-launcher: pod IP, in-cluster DNS, then ClusterIP."""
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: str | None) -> None:
        text = (url or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        urls.append(text)

    for host in _pod_http_hosts():
        add(f"http://{host}")
    add(internal_http_url())
    cluster_ip = _get_service_cluster_ip()
    if cluster_ip:
        add(f"http://{cluster_ip}:8080")
    return urls


def _probe_trino_http(urls: list[str]) -> tuple[bool, str | None]:
    last_error: str | None = None
    for url in urls:
        probe = f"{url.rstrip('/')}/v1/info"
        try:
            with urllib.request.urlopen(probe, timeout=3) as resp:
                if resp.status < 500:
                    return True, None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{probe}: {exc}"
            continue
    return False, last_error


def is_trino_http_up() -> bool:
    ok, _ = _probe_trino_http(_launcher_http_probe_urls())
    return ok


def wait_for_trino() -> None:
    deadline = time.time() + TRINO_STARTUP_TIMEOUT_SECONDS
    next_status_log = time.time()
    last_probe_error: str | None = None
    while time.time() < deadline:
        ok, last_probe_error = _probe_trino_http(_launcher_http_probe_urls())
        if ok:
            _write_solomon_endpoints(get_connection_info())
            return
        if time.time() >= next_status_log:
            print(
                "Waiting for Trino HTTP on port 8080. "
                f"Pod status: {_pod_status_summary()}."
            )
            if last_probe_error:
                print(f"Latest Trino HTTP probe: {last_probe_error}")
            next_status_log = time.time() + 60
        if _pod_has_fatal_failure():
            diagnostics = _pod_diagnostics_text()
            logs = _pod_logs()
            detail = diagnostics or f" Pod status: {_pod_status_summary()}."
            if logs:
                detail += f"\nRecent pod logs:\n{logs[-3000:]}"
            raise RuntimeError(
                "Trino pod failed during startup (see diagnostics below).\n" + detail
            )
        time.sleep(10)
    logs = _pod_logs()
    detail = _pod_diagnostics_text() or f" Pod status: {_pod_status_summary()}."
    if logs:
        detail += f"\nRecent pod logs:\n{logs[-3000:]}"
    raise RuntimeError(f"Trino did not become ready within timeout.\n{detail}")


def _write_solomon_endpoints(info: dict) -> None:
    try:
        from solomon.trino.endpoints_file import write_endpoints

        payload = {
            "internal_http": info.get("internal_http"),
            "http_hosts": info.get("http_hosts") or [],
            "service_name": get_service_name(),
            "catalog": TRINO_CATALOG_NAME,
            "duckdb_file": info.get("duckdb_file") or DUCKDB_FILE,
        }
        path = write_endpoints(payload)
        print(f"Wrote Solomon Trino endpoints to {path}")
        hosts = payload["http_hosts"]
        if hosts:
            print(
                "Solomon TRINO_ENDPOINT (if DNS fails): "
                f"http://{hosts[0]}"
            )
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
        "duckdb_file": str(_deploy_ctx.get("duckdb_file") or DUCKDB_FILE),
        "duckdb_seed_path": str(_duckdb_project_path()),
        "use_pvc": bool(_deploy_ctx.get("use_pvc")),
        "pvc_claim": _deploy_ctx.get("pvc_claim"),
        "pod_status": _pod_status_summary(),
        "pod_logs": _pod_logs(tail_lines=80),
        "k8s_events": _get_k8s_events(),
        "supervisor_phase": _supervisor_state.get("phase"),
        "supervisor_error": _supervisor_state.get("error"),
    }
    info["cluster_ip"] = _get_service_cluster_ip()
    info["http_hosts"] = _collect_http_hosts()
    info["launcher_probe_urls"] = _launcher_http_probe_urls()
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


def _print_trino_env_hints(info: dict) -> None:
    from solomon.trino.env_hints import format_internal_trino_env_hints

    lines = format_internal_trino_env_hints(
        status=info.get("status"),
        http_hosts=info.get("http_hosts"),
        internal_http=info.get("internal_http"),
        cluster_ip=info.get("cluster_ip"),
    )
    for line in lines:
        print(line)


def _print_early_trino_endpoint_hint() -> None:
    print(f"Warehouse Trino internal DNS: {internal_http_url()}")
    cluster_ip = _get_service_cluster_ip()
    if cluster_ip:
        print(
            f"Warehouse Trino Service ClusterIP: http://{cluster_ip}:8080 "
            "(set TRINO_ENDPOINT on Solomon if DNS fails)"
        )
    pod_hosts = _pod_http_hosts()
    if pod_hosts:
        primary = pod_hosts[0]
        host_part, _, port_part = primary.rpartition(":")
        port = port_part if port_part.isdigit() else "8080"
        print(
            f"Warehouse Trino pod IP (launcher only): http://{host_part}:{port}"
        )


def print_connection_info() -> None:
    info = get_connection_info()
    if info.get("status") == "running":
        _write_solomon_endpoints(info)
    print("\n=== Warehouse (Trino + DuckDB) Connection Info ===")
    _print_trino_env_hints(info)
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
        _print_early_trino_endpoint_hint()
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
        diagnostics = _pod_diagnostics_text()
        print(f"Warehouse supervisor error: {exc}")
        if diagnostics:
            print(diagnostics)
        if logs:
            print(f"Latest warehouse pod logs:\n{logs[-5000:]}")
        _supervisor_state["phase"] = "error"
        _supervisor_state["error"] = str(exc)
