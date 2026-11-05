"""Knowledge RAG Agent 用の既定ツール (sql / graph / doc)。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from solomon.tools.graph_cypher_query import GraphCypherQueryTool, validate_readonly_cypher
from solomon.opensearch.doc_index import build_doc_search_tool_description
from solomon.tools.opensearch import DocumentSearchTool
from solomon.tools.sql_guard import validate_readonly_sql
from solomon.tools.text2sql import Text2SQLTool, execute_readonly_sql_with_retry
from solomon.transport.config import get_trino_config
from solomon.transport.user_context import UserContext

_VARLENGTH_RE = re.compile(r"\*(\d+)\.\.(\d+)")
_CYPHER_STRING_RE = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
_CYPHER_PARAM_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


def missing_cypher_params(cypher: str, params: dict[str, Any] | None) -> list[str]:
    """``$name`` のうち params に値が無いもの（文字列リテラル内は除く）。"""
    body = _CYPHER_STRING_RE.sub("''", cypher)
    given = {k for k, v in (params or {}).items() if v is not None}
    seen: list[str] = []
    for name in _CYPHER_PARAM_RE.findall(body):
        if name not in given and name not in seen:
            seen.append(name)
    return seen


def clamp_cypher_varlength(cypher: str, *, max_hops: int = 8) -> str:
    """可変長パス ``*lo..hi`` の上限を ``max_hops`` に抑える。"""

    def _repl(match: re.Match[str]) -> str:
        lo = int(match.group(1))
        hi = min(int(match.group(2)), max_hops)
        lo = min(lo, hi)
        return f"*{lo}..{hi}"

    return _VARLENGTH_RE.sub(_repl, cypher)


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[[dict[str, Any]], dict[str, Any]]

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _doc_hit_from_os_result(raw: dict[str, Any]) -> dict[str, Any]:
    doc_id = raw.get("doc_id") or raw.get("fq_name") or raw.get("id") or ""
    title = raw.get("title") or doc_id or "document"
    snippet = (raw.get("snippet") or raw.get("text") or "")[:500]
    score = raw.get("score")
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    if not metadata:
        metadata = {
            k: v
            for k, v in raw.items()
            if k
            not in (
                "snippet",
                "score",
                "title",
                "text",
                "doc_type_label",
                "match",
            )
        }
    out: dict[str, Any] = {
        "doc_id": str(doc_id),
        "title": str(title),
        "snippet": str(snippet),
        "score": float(score) if score is not None else None,
        "metadata": metadata,
    }
    for key in (
        "chunk_id",
        "doc_type",
        "doc_type_label",
        "doc_date",
        "index",
    ):
        if raw.get(key) not in (None, ""):
            out[key] = raw.get(key)
    return out


def run_sql_query(
    user_ctx: Optional[UserContext],
    *,
    question: str,
    sql: str | None = None,
    use_search_context: bool = True,
) -> dict[str, Any]:
    if sql:
        trino_cfg = get_trino_config()
        if trino_cfg is None:
            return {"status": "error", "message": "Trino is not configured."}
        pipeline = execute_readonly_sql_with_retry(
            user_ctx,
            question=question,
            catalog=trino_cfg.catalog,
            schema=trino_cfg.schema,
            max_rows=50,
            sql=sql,
        )
        if pipeline.get("status") != "ok":
            return {
                "status": "error",
                "message": pipeline.get("message", "Trino query failed"),
                "error_code": pipeline.get("error_code"),
                "attempts": pipeline.get("attempts") or [],
            }
        rows = pipeline.get("rows") or []
        return {
            "status": "ok",
            "sql": pipeline.get("sql"),
            "columns": pipeline.get("columns"),
            "rows": rows[:50],
            "row_count": pipeline.get("row_count", len(rows)),
            "attempts": pipeline.get("attempts") or [],
        }

    tool = Text2SQLTool()
    result = tool.run(
        user_ctx=user_ctx,
        question=question,
        max_rows=50,
        use_search_context=use_search_context,
    )
    if result.get("status") != "ok":
        return {
            "status": "error",
            "message": result.get("message", "text2sql failed"),
            "error_code": result.get("error_code"),
            "hint": "テーブルスキーマの列名で SQL を書き、sql 引数に渡して再実行する。",
        }
    rows = result.get("rows") or []
    return {
        "status": "ok",
        "sql": result.get("sql"),
        "columns": result.get("columns"),
        "rows": rows[:50],
        "row_count": result.get("row_count", len(rows)),
        "reasoning": result.get("reasoning"),
    }


def run_graph_query(
    user_ctx: Optional[UserContext],
    *,
    cypher: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cypher = clamp_cypher_varlength(cypher)
    validation = validate_readonly_cypher(cypher)
    if validation:
        return {"status": "error", "message": validation}
    missing = missing_cypher_params(cypher, params)
    if missing:
        example = ", ".join(f'"{name}": "<値>"' for name in missing)
        return {
            "status": "error",
            "message": (
                "Cypher のパラメータ "
                + ", ".join(f"${name}" for name in missing)
                + f" に値がありません。params={{{example}}} を付けて再実行する。"
            ),
        }
    tool = GraphCypherQueryTool()
    result = tool.run(user_ctx=user_ctx, cypher=cypher, params=params or {})
    if result.get("status") != "ok":
        return {
            "status": "error",
            "message": result.get("message", "graph query failed"),
            "error_code": result.get("error_code"),
        }
    records = result.get("records") or []
    return {
        "status": "ok",
        "records": records[:200],
        "count": result.get("count", len(records)),
        "truncated": len(records) > 200,
        "cypher": cypher,
        "params": params or {},
    }


def run_doc_search(
    user_ctx: Optional[UserContext],
    *,
    query: str,
    top_k: int = 8,
    filters: dict[str, Any] | None = None,
    mode: str = "hybrid",
) -> dict[str, Any]:
    top_k = max(1, min(int(top_k), 20))
    tool = DocumentSearchTool()
    from solomon.opensearch.query_expansion import doc_search_expansion_enabled

    result = tool.run(
        user_ctx=user_ctx,
        query=query,
        top_k=top_k,
        filters=filters,
        mode=mode,
        expand=doc_search_expansion_enabled(),
    )
    if result.get("status") != "ok":
        return {
            "status": "error",
            "message": result.get("message", "doc search failed"),
            "error_code": result.get("error_code"),
            "documents": [],
            "warnings": result.get("warnings") or [],
        }
    raw_results = result.get("documents") or []
    documents = [_doc_hit_from_os_result(r) for r in raw_results[:top_k]]
    return {
        "status": "ok",
        "query": query,
        "top_k": top_k,
        "mode": mode,
        "documents": documents,
        "count": len(documents),
        "warnings": result.get("warnings") or [],
        "expanded_queries": result.get("expanded_queries") or [],
    }


def default_agent_tools(
    user_ctx: Optional[UserContext],
    enabled_sources: frozenset[str] | None = None,
) -> list[AgentTool]:
    """有効ソースに応じたツール一覧。``user_ctx`` はクロージャで各 execute に渡す。"""
    if enabled_sources is None:
        enabled_sources = frozenset({"table", "graph", "search"})
    use_search_in_sql = "search" in enabled_sources
    tools: list[AgentTool] = []

    if "table" in enabled_sources:

        def _sql(args: dict[str, Any]) -> dict[str, Any]:
            return run_sql_query(
                user_ctx,
                question=str(args.get("question") or ""),
                sql=args.get("sql"),
                use_search_context=use_search_in_sql,
            )

        tools.append(
            AgentTool(
                name="sql_query",
            description=(
                "Lakehouse (Trino) で読み取り専用 SQL を実行する。"
                "通常は sql にテーブルスキーマの列名で書いた SELECT / WITH を渡す。"
                "sql を省略したときだけ question から SQL を生成する（遅く、条件が落ちやすい）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "このクエリで確かめたいこと（ログ・SQL 生成時に使用）",
                    },
                    "sql": {
                        "type": "string",
                        "description": "実行する SELECT / WITH クエリ（推奨）",
                    },
                },
                "required": ["question"],
            },
                execute=_sql,
            )
        )

    if "graph" in enabled_sources:

        def _graph(args: dict[str, Any]) -> dict[str, Any]:
            params = args.get("params")
            if params is not None and not isinstance(params, dict):
                return {"status": "error", "message": "params must be an object"}
            return run_graph_query(
                user_ctx,
                cypher=str(args.get("cypher") or ""),
                params=params if isinstance(params, dict) else {},
            )

        tools.append(
            AgentTool(
                name="graph_query",
            description=(
                "PuppyGraph で読み取り専用 openCypher を実行する。"
                "つながり・多段トレースに使う。可変長は *1..8 まで。"
                "多段の追跡は 1 段ずつ繰り返さず、可変長パス 1 回で末端まで集計する。"
                "Cypher 内の $名前 には params で値を渡す。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "cypher": {"type": "string", "description": "MATCH ... RETURN ..."},
                    "params": {
                        "type": "object",
                        "description": "Cypher パラメータ",
                        "additionalProperties": True,
                    },
                },
                "required": ["cypher"],
            },
                execute=_graph,
            )
        )

    if "search" in enabled_sources:

        def _doc(args: dict[str, Any]) -> dict[str, Any]:
            filters = args.get("filters")
            if filters is not None and not isinstance(filters, dict):
                return {"status": "error", "message": "filters must be an object"}
            return run_doc_search(
                user_ctx,
                query=str(args.get("query") or ""),
                top_k=int(args.get("top_k") or 8),
                filters=filters if isinstance(filters, dict) else None,
                mode=str(args.get("mode") or "hybrid"),
            )

        tools.append(
            AgentTool(
                name="doc_search",
            description=build_doc_search_tool_description(),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "検索クエリ"},
                    "mode": {
                        "type": "string",
                        "enum": ["keyword", "vector", "hybrid"],
                        "description": "Search mode",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "最大件数 (1–20)",
                        "default": 8,
                    },
                    "filters": {
                        "type": "object",
                        "description": "将来用メタデータフィルタ",
                        "additionalProperties": True,
                    },
                },
                "required": ["query"],
            },
                execute=_doc,
            )
        )

    return tools


def cache_key(name: str, args: dict[str, Any]) -> str:
    return json.dumps({"name": name, "args": args}, sort_keys=True, default=str)


__all__ = [
    "AgentTool",
    "cache_key",
    "clamp_cypher_varlength",
    "default_agent_tools",
    "missing_cypher_params",
    "run_doc_search",
    "run_graph_query",
    "run_sql_query",
    "validate_readonly_sql",
]
