"""OpenSearch Launcher — co-located OpenSearch for CML demo deployments."""

from __future__ import annotations

import html
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from utils.opensearch_utils import get_connection_info, run_opensearch_supervisor


def _render_status_page(info: dict) -> str:
    rows = [
        ("Status", info.get("status")),
        ("Mode", os.getenv("SOLOMON_OPENSEARCH_MODE", "datahub")),
        ("Internal HTTP", info.get("internal_http")),
        ("HTTP Hosts", ", ".join(info.get("http_hosts") or [])),
        ("Service", info.get("service_name")),
        ("Namespace", info.get("namespace")),
        ("Pod Status", info.get("pod_status")),
        ("Supervisor Phase", info.get("supervisor_phase")),
        ("Message", info.get("message")),
        ("Supervisor Error", info.get("supervisor_error")),
    ]
    body = "".join(
        f"<tr><th>{html.escape(str(label))}</th>"
        f"<td><pre>{html.escape(str(value or ''))}</pre></td></tr>"
        for label, value in rows
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>OpenSearch Launcher</title></head>
<body>
<h1>OpenSearch Launcher</h1>
<p>CML demo mode uses <code>SOLOMON_OPENSEARCH_MODE=cml</code>.
Production uses <code>datahub</code> with Data Hub Semantic Search.</p>
<table>{body}</table>
</body></html>"""


class OpenSearchLauncherHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        info = get_connection_info()
        if self.path in ("/", "/status"):
            payload = _render_status_page(info).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/health":
            code = 200 if info.get("status") == "running" else 503
            payload = json.dumps(info).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404)

    def log_message(self, format: str, *args) -> None:
        return


class ReuseAddrHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    port = int(os.getenv("CDSW_APP_PORT") or "8091")
    bind_host = os.getenv("OPENSEARCH_LAUNCHER_BIND_HOST", "127.0.0.1")
    print(f"Starting OpenSearch Launcher on {bind_host}:{port}")
    server = ReuseAddrHTTPServer((bind_host, port), OpenSearchLauncherHandler)
    server.daemon_threads = True
    threading.Thread(target=run_opensearch_supervisor, daemon=True).start()
    server.serve_forever()
