"""PuppyGraph Launcher — co-located PuppyGraph for PUPPYGRAPH_MODE=internal."""

from __future__ import annotations

import html
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from utils.puppygraph_utils import get_connection_info, run_puppygraph_supervisor


def _render_status_page(info: dict) -> str:
    rows = [
        ("Status", info.get("status")),
        ("Mode", os.getenv("PUPPYGRAPH_MODE") or "internal"),
        ("Internal Bolt", info.get("internal_bolt")),
        ("Bolt Hosts", ", ".join(info.get("bolt_hosts") or [])),
        ("Web UI (in-cluster)", info.get("internal_http")),
        ("Service", info.get("service_name")),
        ("Namespace", info.get("namespace")),
        ("Pod Status", info.get("pod_status")),
        ("Supervisor Phase", info.get("supervisor_phase")),
        ("Message", info.get("message")),
        ("Supervisor Error", info.get("supervisor_error")),
    ]
    table_rows: list[str] = []
    for label, value in rows:
        if value in (None, ""):
            continue
        if label == "Pod Status" and info.get("pod_logs"):
            cell = (
                f"<code>{html.escape(str(value))}</code>"
                f"<pre style='max-height:12rem;overflow:auto'>"
                f"{html.escape(str(info.get('pod_logs'))[-2000:])}</pre>"
            )
        else:
            cell = f"<code>{html.escape(str(value))}</code>"
        table_rows.append(
            f"<tr><th>{html.escape(label)}</th><td>{cell}</td></tr>"
        )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta http-equiv="refresh" content="10">
<title>PuppyGraph Launcher</title></head>
<body>
<h1>PuppyGraph Launcher</h1>
<p>Internal mode runs <strong>PuppyGraph</strong> (Bolt 7687 / Web UI 8081) on Kubernetes。
Status が <code>running</code> になったら <code>.solomon/puppygraph_endpoints.json</code>
が更新されます。<strong>Solomon Application を Restart</strong> して Graph タブを開いてください。
catalog / graph schema は PuppyGraph Web UI で定義します（Trino 等への接続は post-deploy）。</p>
<table>{''.join(table_rows)}</table>
</body></html>"""


class PuppyGraphLauncherHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/health", "/healthz"):
            info = get_connection_info()
            code = 200 if info.get("status") == "running" else 503
            payload = json.dumps(info).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path in ("/", "/index.html", "/launcher", "/launcher/", "/status", "/api/info"):
            info = get_connection_info()
            body = _render_status_page(info).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, fmt: str, *args) -> None:
        return


class ReuseAddrHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _wait_for_app_port(timeout_sec: float = 60.0) -> int:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        raw = (os.environ.get("CDSW_APP_PORT") or "").strip()
        if raw:
            try:
                port = int(raw)
            except ValueError:
                port = 0
            if port > 0:
                print(f"[puppygraph-launcher] CDSW_APP_PORT={port}", flush=True)
                return port
        time.sleep(0.5)
    raise RuntimeError(
        "CDSW_APP_PORT was not assigned within "
        f"{timeout_sec:.0f}s (BrowserSvcs may log Duplicate port 0)"
    )


if __name__ == "__main__":
    port = _wait_for_app_port()
    bind_host = os.getenv("PUPPYGRAPH_LAUNCHER_BIND_HOST", "127.0.0.1")
    print(f"Starting PuppyGraph Launcher on {bind_host}:{port}", flush=True)
    server = ReuseAddrHTTPServer((bind_host, port), PuppyGraphLauncherHandler)
    server.daemon_threads = True
    threading.Thread(target=run_puppygraph_supervisor, daemon=True).start()
    server.serve_forever()
