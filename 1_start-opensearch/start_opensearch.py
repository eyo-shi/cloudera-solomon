"""OpenSearch Launcher — co-located OpenSearch + Dashboards for internal mode."""

from __future__ import annotations

import html
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin, urlparse

from utils.opensearch_utils import (
    DASHBOARDS_BASE_PATH,
    build_proxied_dashboards_path,
    get_connection_info,
    internal_dashboards_url,
    is_dashboards_http_up,
    run_opensearch_supervisor,
)

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

STRIPPED_RESPONSE_HEADERS = HOP_BY_HOP_HEADERS | {
    "content-encoding",
    "content-length",
    "content-security-policy",
    "content-security-policy-report-only",
}


def _render_status_page(info: dict) -> str:
    rows = [
        ("Status", info.get("status")),
        ("Mode", os.getenv("OPENSEARCH_MODE") or os.getenv("SOLOMON_OPENSEARCH_MODE", "internal")),
        ("OpenSearch Dashboards", info.get("proxied_dashboards_path")),
        ("Internal HTTP", info.get("internal_http")),
        ("Internal Dashboards", info.get("internal_dashboards")),
        ("HTTP Hosts", ", ".join(info.get("http_hosts") or [])),
        ("Service", info.get("service_name")),
        ("Namespace", info.get("namespace")),
        ("Pod Status", info.get("pod_status")),
        ("Dashboards Ready", info.get("dashboards_ready")),
        ("Supervisor Phase", info.get("supervisor_phase")),
        ("Message", info.get("message")),
        ("Supervisor Error", info.get("supervisor_error")),
    ]
    table_rows: list[str] = []
    for label, value in rows:
        if value in (None, ""):
            continue
        if label == "OpenSearch Dashboards" and value:
            cell = (
                f'<a href="{html.escape(str(value))}">Open OpenSearch Dashboards</a> '
                "(recommended)"
            )
        elif label == "Pod Status" and info.get("pod_logs"):
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
<title>OpenSearch Launcher</title></head>
<body>
<h1>OpenSearch Launcher</h1>
<p>Internal mode runs OpenSearch plus <strong>OpenSearch Dashboards</strong> (Neo4j Browser 相当の管理 UI)。
Status が <code>running</code> になったら <strong>Open OpenSearch Dashboards</strong> を開いてください。</p>
<table>{''.join(table_rows)}</table>
</body></html>"""


def _rewrite_location_header(value: str, public_host: str | None) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        path = parsed.path or "/"
        if public_host and path.startswith(DASHBOARDS_BASE_PATH):
            return path + (f"?{parsed.query}" if parsed.query else "")
        return value
    return value


class OpenSearchLauncherHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._handle_request("GET")

    def do_POST(self) -> None:
        self._handle_request("POST")

    def do_PUT(self) -> None:
        self._handle_request("PUT")

    def do_DELETE(self) -> None:
        self._handle_request("DELETE")

    def do_PATCH(self) -> None:
        self._handle_request("PATCH")

    def do_OPTIONS(self) -> None:
        self._handle_request("OPTIONS")

    def _current_request_host(self) -> str | None:
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host")
        if not host:
            return None
        return host.split(",")[0].strip()

    def _handle_request(self, method: str) -> None:
        path = urlparse(self.path).path
        if method == "OPTIONS":
            self.send_response(204)
            self.end_headers()
            return
        if path in ("/health", "/healthz"):
            info = get_connection_info()
            code = 200 if info.get("status") == "running" else 503
            payload = json.dumps(info).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path in ("/launcher", "/launcher/", "/status"):
            payload = _render_status_page(get_connection_info()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path in ("", "/") and method == "GET":
            if is_dashboards_http_up():
                target = build_proxied_dashboards_path()
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()
                return
            payload = _render_status_page(get_connection_info()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path.startswith(DASHBOARDS_BASE_PATH):
            self._proxy_dashboards(method)
            return
        self.send_error(404)

    def _proxy_dashboards(self, method: str) -> None:
        if not is_dashboards_http_up():
            payload = _render_status_page(get_connection_info()).encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else None
        target = urljoin(
            f"{internal_dashboards_url().rstrip('/')}/",
            self.path.lstrip("/"),
        )
        request = urllib.request.Request(
            target,
            data=body,
            method=method,
        )
        for header, value in self.headers.items():
            header_lower = header.lower()
            if header_lower in HOP_BY_HOP_HEADERS or header_lower in ("host", "accept-encoding"):
                continue
            request.add_header(header, value)
        request.add_header("Accept-Encoding", "identity")

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body_bytes = response.read()
                self.send_response(response.status)
                public_host = self._current_request_host()
                for header, value in response.headers.items():
                    header_lower = header.lower()
                    if header_lower in STRIPPED_RESPONSE_HEADERS:
                        continue
                    if header_lower == "location":
                        value = _rewrite_location_header(value, public_host)
                    self.send_header(header, value)
                self.send_header("Content-Length", str(len(body_bytes)))
                self.end_headers()
                self.wfile.write(body_bytes)
        except urllib.error.HTTPError as exc:
            body_bytes = exc.read()
            self.send_response(exc.code)
            for header, value in exc.headers.items():
                header_lower = header.lower()
                if header_lower in STRIPPED_RESPONSE_HEADERS:
                    continue
                self.send_header(header, value)
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        except Exception as exc:
            self.send_error(502, f"OpenSearch Dashboards proxy failed: {exc}")

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
