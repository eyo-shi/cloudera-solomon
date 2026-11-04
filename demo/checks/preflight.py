"""デモ環境の事前確認（外部書き込みはテストインデックスのみ）。"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

PREFLIGHT_TEST_INDEX = "solomon-demo-preflight-test"


@dataclass
class PreflightRow:
    check: str
    status: str  # pass | fail | skip | warn
    detail: str
    recommendation: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "check": self.check,
            "status": self.status,
            "detail": self.detail,
            "recommendation": self.recommendation,
        }


def recommend_docs_analyzer(plugins_text: str) -> str:
    """OpenSearch _cat/plugins 出力から analyzer 推奨。"""
    if "analysis-kuromoji" in plugins_text.lower():
        return "kuromoji"
    return "cjk"


def recommend_iceberg_load_method(catalog_names: list[str]) -> str:
    lower = {c.lower() for c in catalog_names}
    return "a" if "hive" in lower else "b"


def parse_opensearch_version(info: dict[str, Any]) -> str:
    v = info.get("version") or {}
    if isinstance(v, dict):
        return str(v.get("number") or v.get("distribution") or "")
    return str(v)


def opensearch_version_below_29(version: str) -> bool:
    parts = version.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return (major, minor) < (2, 9)
    except (ValueError, IndexError):
        return False


def format_table(rows: list[PreflightRow]) -> str:
    headers = ("check", "status", "detail", "recommendation")
    data = [headers] + [(r.check, r.status, r.detail[:120], r.recommendation[:80]) for r in rows]
    widths = [max(len(str(row[i])) for row in data) for i in range(4)]
    lines = []
    for i, row in enumerate(data):
        line = " | ".join(str(row[j]).ljust(widths[j]) for j in range(4))
        lines.append(line)
        if i == 0:
            lines.append("-+-".join("-" * w for w in widths))
    return "\n".join(lines)


def check_ossie_validate(semantic_root: str | None) -> PreflightRow:
    root = semantic_root or os.environ.get("SOLOMON_SEMANTIC_ROOT") or "./semantic"
    proc = subprocess.run(
        [sys.executable, "-m", "solomon.semantic", "validate", "--root", root],
        capture_output=True,
        text=True,
    )
    ok = proc.returncode == 0
    detail = (proc.stdout or proc.stderr).strip().split("\n")[-3:]
    return PreflightRow(
        check="ossie_validate",
        status="pass" if ok else "fail",
        detail="; ".join(detail)[:500],
        recommendation="SOLOMON_SEMANTIC_ROOT を demo/<domain>/semantic に合わせる",
    )


def check_trino_catalogs(
    query_fn: Callable[[str], Any] | None = None,
) -> list[PreflightRow]:
    if query_fn is None:
        try:
            from demo.loader.trino_runtime import make_trino_callbacks

            _, query_fn = make_trino_callbacks()
        except Exception as exc:  # noqa: BLE001
            return [
                PreflightRow(
                    check="trino_catalogs",
                    status="skip",
                    detail=str(exc),
                    recommendation="TRINO_MODE=external, TRINO_URL/HOST, 認証を設定",
                )
            ]
    try:
        rows = query_fn("SHOW CATALOGS")
        names = [str(r[0]) for r in rows] if rows else []
        method = recommend_iceberg_load_method(names)
        rec = f"demo.loader --iceberg-method {method}（hive 無しなら b + CREATE SCHEMA 権限確認）"
        return [
            PreflightRow(
                check="trino_show_catalogs",
                status="pass",
                detail=f"catalogs={names}",
                recommendation=rec,
            ),
            PreflightRow(
                check="trino_iceberg_schema",
                status="pass",
                detail="SHOW SCHEMAS FROM iceberg は手動確認推奨",
                recommendation=f"TRINO_SCHEMA={os.environ.get('TRINO_SCHEMA', 'demo')}",
            ),
        ]
    except Exception as exc:  # noqa: BLE001
        return [
            PreflightRow(
                check="trino_catalogs",
                status="fail",
                detail=str(exc),
                recommendation="CDW Trino 接続・Ranger SELECT/CREATE 権限を確認",
            )
        ]


def check_tcp_reachability(host: str, port: int, label: str) -> PreflightRow:
    try:
        with socket.create_connection((host, port), timeout=5):
            return PreflightRow(check=label, status="pass", detail=f"{host}:{port} open")
    except OSError as exc:
        return PreflightRow(
            check=label,
            status="fail",
            detail=str(exc),
            recommendation=f"{label} の URL / ファイアウォール / Service を確認",
        )


def check_puppygraph_reachability() -> list[PreflightRow]:
    rows: list[PreflightRow] = []
    uri = os.environ.get("PUPPYGRAPH_URI") or ""
    if uri:
        parsed = urlparse(uri if "://" in uri else f"bolt://{uri}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 7687
        rows.append(check_tcp_reachability(host, port, "puppygraph_bolt"))
    else:
        rows.append(
            PreflightRow(
                check="puppygraph_bolt",
                status="skip",
                detail="PUPPYGRAPH_URI unset",
                recommendation="PUPPYGRAPH_URI=bolt://host:7687",
            )
        )
    http_url = (os.environ.get("PUPPYGRAPH_HTTP_URL") or "").strip()
    if not http_url:
        port = int(os.environ.get("PUPPYGRAPH_HTTP_PORT") or "8081")
        host = urlparse(uri).hostname if uri else "127.0.0.1"
        http_url = f"http://{host}:{port}"
    try:
        parsed = urlparse(http_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8081
        rows.append(check_tcp_reachability(host, port, "puppygraph_http"))
    except Exception as exc:  # noqa: BLE001
        rows.append(PreflightRow("puppygraph_http", "fail", str(exc), "PUPPYGRAPH_HTTP_URL"))
    return rows


def check_opensearch(
    *,
    allow_write: bool,
    client_factory: Callable[[], Any] | None = None,
) -> list[PreflightRow]:
    rows: list[PreflightRow] = []
    try:
        if client_factory is not None:
            client = client_factory()
        else:
            from solomon.opensearch.client import build_client
            from solomon.transport.config import get_opensearch_config

            cfg = get_opensearch_config()
            if cfg is None:
                return [
                    PreflightRow(
                        check="opensearch_config",
                        status="skip",
                        detail="OPENSEARCH_* not configured",
                        recommendation="OPENSEARCH_MODE=external + CONNECTION_NAME or ENDPOINT",
                    )
                ]
            client = build_client(cfg)
        info = client.info()
        ver = parse_opensearch_version(info)
        rows.append(
            PreflightRow(
                check="opensearch_version",
                status="pass",
                detail=f"version={ver}",
                recommendation=(
                    "k-NN pre-filter 注意 (2.9 未満)"
                    if opensearch_version_below_29(ver)
                    else "OK"
                ),
            )
        )
        try:
            plugins = client.cat.plugins(format="json")
            plugin_text = json.dumps(plugins)
        except Exception:  # noqa: BLE001
            plugin_text = ""
        analyzer = recommend_docs_analyzer(plugin_text)
        rows.append(
            PreflightRow(
                check="opensearch_analyzer",
                status="pass",
                detail=f"plugins_sample={plugin_text[:200]}",
                recommendation=f"OPENSEARCH_DOCS_ANALYZER={analyzer}",
            )
        )
        if allow_write:
            idx = PREFLIGHT_TEST_INDEX
            body = {"settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}}}
            try:
                if client.indices.exists(index=idx):
                    client.indices.delete(index=idx)
                client.indices.create(index=idx, body=body)
                client.indices.delete(index=idx)
                rows.append(
                    PreflightRow(
                        check="opensearch_index_acl",
                        status="pass",
                        detail=f"created/deleted {idx}",
                        recommendation="Ranger インデックス作成権限 OK",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    PreflightRow(
                        check="opensearch_index_acl",
                        status="fail",
                        detail=str(exc),
                        recommendation="管理者にインデックス作成を依頼 → demo.loader --skip-create",
                    )
                )
        else:
            rows.append(
                PreflightRow(
                    check="opensearch_index_acl",
                    status="skip",
                    detail="--no-write",
                    recommendation="権限確認時は preflight を --no-write なしで再実行",
                )
            )
    except Exception as exc:  # noqa: BLE001
        rows.append(PreflightRow("opensearch", "fail", str(exc), "OPENSEARCH_ENDPOINT / 認証"))
    return rows


def check_embedding(
    *,
    embed_fn: Callable[[str], list[float] | None] | None = None,
    max_chars: int | None = None,
) -> PreflightRow:
    max_c = max_chars or int(os.environ.get("DEMO_EMBED_MAX_CHARS", "2000"))
    text_short = "疎通確認"
    text_long = "x" * max_c
    try:
        if embed_fn is None:
            from solomon.opensearch.embeddings import try_embed

            # 検索側 (query) と索引側 (passage) の両方を確認する
            def query_fn(text: str) -> list[float] | None:
                return try_embed(text, purpose="query")

            def passage_fn(text: str) -> list[float] | None:
                return try_embed(text, purpose="passage")
        else:
            query_fn = passage_fn = embed_fn
        v1 = query_fn(text_short)
        v2 = passage_fn(text_long)
        if v1 is None:
            return PreflightRow(
                check="embedding",
                status="fail",
                detail="short embed returned None",
                recommendation=(
                    "SOLOMON_LLM_EMBEDDING_MODEL (または _QUERY_MODEL / _PASSAGE_MODEL)"
                    " と BASE_URL / API キー"
                ),
            )
        dim = len(v1)
        exp_dim = int(os.environ.get("OPENSEARCH_EMBEDDING_DIM", "1024"))
        ok_dim = dim == exp_dim
        long_ok = v2 is not None
        same_dim = v2 is None or len(v2) == dim
        status = "pass" if ok_dim and long_ok and same_dim else "warn"
        passage_dim = len(v2) if v2 is not None else None
        return PreflightRow(
            check="embedding",
            status=status,
            detail=(
                f"dim={dim} passage_dim={passage_dim} expected={exp_dim}"
                f" long_ok={long_ok} max_chars={max_c}"
            ),
            recommendation=(
                f"OPENSEARCH_EMBEDDING_DIM={dim} または SOLOMON_LLM_EMBEDDING_DIMENSIONS={exp_dim};"
                f" DEMO_EMBED_MAX_CHARS={max_c}"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return PreflightRow("embedding", "fail", str(exc), "SOLOMON_LLM_EMBEDDING_* を設定")


def check_llm_function_calling(
    probe_fn: Callable[[], bool] | None = None,
) -> PreflightRow:
    if probe_fn is not None:
        ok = probe_fn()
        return PreflightRow(
            check="llm_function_calling",
            status="pass" if ok else "warn",
            detail="probe_fn",
            recommendation="SOLOMON_RAG_TOOL_MODE=native" if ok else "SOLOMON_RAG_TOOL_MODE=json",
        )
    try:
        from solomon.rag.agent import _native_turn
        from solomon.rag.agent_tools import default_agent_tools
        from solomon.transport.user_context import UserContext

        tools = default_agent_tools(UserContext(user_name="preflight"), frozenset({"search"}))
        openai_tools = [t.to_openai_tool() for t in tools[:1]]
        msg = _native_turn(
            [{"role": "user", "content": "Reply with a tool call listing one document."}],
            openai_tools,
            max_tokens=64,
            temperature=0,
            timeout=30.0,
        )
        ok = bool(msg and (msg.get("tool_calls") or msg.get("function_call")))
        return PreflightRow(
            check="llm_function_calling",
            status="pass" if ok else "warn",
            detail="tool_calls present" if ok else "no tool_calls in response",
            recommendation="SOLOMON_RAG_TOOL_MODE=native" if ok else "SOLOMON_RAG_TOOL_MODE=json",
        )
    except Exception as exc:  # noqa: BLE001
        return PreflightRow(
            check="llm_function_calling",
            status="skip",
            detail=str(exc)[:300],
            recommendation="SOLOMON_RAG_TOOL_MODE=json; SOLOMON_LLM_AGENT_RAG_AGENT_MODEL を確認",
        )


def run_preflight(
    *,
    semantic_root: str | None = None,
    allow_write: bool = True,
    trino_query: Callable[[str], Any] | None = None,
    opensearch_client_factory: Callable[[], Any] | None = None,
    embed_fn: Callable[[str], list[float] | None] | None = None,
    llm_probe: Callable[[], bool] | None = None,
) -> list[PreflightRow]:
    rows: list[PreflightRow] = []
    rows.append(check_ossie_validate(semantic_root))
    rows.extend(check_trino_catalogs(trino_query))
    rows.extend(check_puppygraph_reachability())
    rows.extend(check_opensearch(allow_write=allow_write, client_factory=opensearch_client_factory))
    rows.append(check_embedding(embed_fn=embed_fn))
    rows.append(check_llm_function_calling(probe_fn=llm_probe))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demo.checks.preflight")
    parser.add_argument(
        "--semantic-root",
        default=None,
        help="Ossie root (default: SOLOMON_SEMANTIC_ROOT)",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="OpenSearch テストインデックス作成をスキップ",
    )
    parser.add_argument("--json", action="store_true", help="JSON 出力")
    args = parser.parse_args(argv)
    rows = run_preflight(semantic_root=args.semantic_root, allow_write=not args.no_write)
    if args.json:
        print(json.dumps([r.to_dict() for r in rows], ensure_ascii=False, indent=2))
    else:
        print(format_table(rows))
    failed = any(r.status == "fail" for r in rows)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
