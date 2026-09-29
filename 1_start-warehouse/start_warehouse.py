"""Warehouse Launcher — co-located Trino + DuckDB for TRINO_MODE=internal."""

from __future__ import annotations

import html
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from utils.warehouse_utils import get_connection_info, run_warehouse_supervisor


def _render_status_page(info: dict) -> str:
    rows = [
        ("Status", info.get("status")),
        ("Mode", os.getenv("TRINO_MODE") or "internal"),
        ("Catalog", info.get("catalog")),
        ("DuckDB file", info.get("duckdb_file")),
        ("Internal HTTP", info.get("internal_http")),
        ("HTTP Hosts", ", ".join(info.get("http_hosts") or [])),
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
<title>Warehouse Launcher</title></head>
<body>
<h1>Warehouse Launcher</h1>
<p>Internal mode runs <strong>Trino</strong> with a <strong>DuckDB</strong> catalog
(Tables タブ / プレビュー用デモ)。Status が <code>running</code> になったら
Solomon Application を再起動するか Tables タブを Refresh してください。</p>
<table>{''.join(table_rows)}</table>
</body></html>"""


class WarehouseLauncherHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            info = get_connection_info()
            body = _render_status_page(info).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/info":
            info = get_connection_info()
            body = json.dumps(info, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    port = int(os.environ.get("CDSW_APP_PORT") or "8090")
    supervisor = threading.Thread(target=run_warehouse_supervisor, daemon=True)
    supervisor.start()
    server = ThreadingHTTPServer(("0.0.0.0", port), WarehouseLauncherHandler)
    print(f"[warehouse-launcher] listening on {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
