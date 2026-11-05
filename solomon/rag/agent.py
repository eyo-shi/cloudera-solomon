"""Knowledge RAG — ReAct 型ツール呼び出しエージェント (litellm 直接)。"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Literal, Optional

import yaml

from solomon.rag.agent_tools import AgentTool, cache_key, default_agent_tools
from solomon.rag.models import (
    KnowledgeRagResult,
    RetrievalBundle,
    RetrievalPlan,
    SourceHit,
)
from solomon.transport.config import get_llm_agent_config, get_trino_config
from solomon.transport.llm import _parse_json_lenient, _text_completion_kwargs
from solomon.transport.llm import strip_reasoning as _strip_reasoning
from solomon.transport.logging import get_logger
from solomon.transport.user_context import UserContext

_logger = get_logger(__name__)

ToolMode = Literal["auto", "native", "json"]
EventCallback = Callable[[dict[str, Any]], None]

_RESULT_MAX_CHARS = 6000
_FINAL_TURN_MAX_TOKENS = 4096
_JSON_SYSTEM_TAIL = (
    "各ターンは必ず次の JSON オブジェクトのどちらか 1 つだけを返す（説明文やコードフェンスは禁止）。\n"
    '1) ツール実行: {{"thought": "...", "action": "<tool名>", "args": {{...}}}}\n'
    '2) 最終回答: {{"thought": "...", "final_answer": "日本語 Markdown"}}\n'
    "利用可能なツール名: {tool_names}"
)


_HISTORY_TURNS_MAX = 3
_HISTORY_PROMPT_MAX_CHARS = 1000
_HISTORY_ANSWER_MAX_CHARS = 2500
_EVIDENCE_HEADING = "\n### 根拠"
_MD_LABEL = r"((?:\\.|[^\]\\])*)"
_SOLOMON_INLINE_LINK_RE = re.compile(r"\[" + _MD_LABEL + r"\]\(solomon://[^)\s]*\)")
_SOLOMON_REF_LINK_RE = re.compile(r"\[" + _MD_LABEL + r"\]\[solomon-[^\]]*\]")
_SOLOMON_REF_DEF_RE = re.compile(r"(?m)^\[[^\]]+\]:\s*solomon://\S*[ \t]*\n?")
_MD_ESCAPE_RE = re.compile(r"\\([\\\[\]])")


def _compact_history_answer(text: str) -> str:
    """過去ターンの回答を履歴用に縮める（自動付与の根拠節と UI 深リンクを落とす）。"""
    body = _strip_reasoning(text)
    cut = body.rfind(_EVIDENCE_HEADING)
    if cut != -1:
        body = body[:cut]

    def label_only(match: re.Match[str]) -> str:
        return _MD_ESCAPE_RE.sub(r"\1", match.group(1))

    body = _SOLOMON_REF_DEF_RE.sub("", body)
    body = _SOLOMON_INLINE_LINK_RE.sub(label_only, body)
    body = _SOLOMON_REF_LINK_RE.sub(label_only, body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if len(body) > _HISTORY_ANSWER_MAX_CHARS:
        body = body[: _HISTORY_ANSWER_MAX_CHARS - 1] + "…"
    return body


def _history_messages(
    history: list[tuple[str, str]] | None,
) -> list[dict[str, Any]]:
    """直近の (質問, 回答) を user / assistant メッセージに変換する。"""
    pairs: list[tuple[str, str]] = []
    for user_text, answer in history or []:
        question = (user_text or "").strip()[:_HISTORY_PROMPT_MAX_CHARS]
        reply = _compact_history_answer(answer or "")
        if question and reply:
            pairs.append((question, reply))
    out: list[dict[str, Any]] = []
    for question, reply in pairs[-_HISTORY_TURNS_MAX:]:
        out.append({"role": "user", "content": question})
        out.append({"role": "assistant", "content": reply})
    return out


_TOOL_CALL_RE = re.compile(
    r"<tool_call>(.*?)(?:</tool_call>|\Z)", re.DOTALL | re.IGNORECASE
)
_XML_FUNCTION_RE = re.compile(
    r"<function=([^>\s]+)\s*>(.*?)(?:</function>|\Z)", re.DOTALL | re.IGNORECASE
)
_XML_PARAM_RE = re.compile(
    r"<parameter=([^>\s]+)\s*>(.*?)(?=</parameter>|<parameter=|</function>|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def _coerce_param_value(raw: str) -> Any:
    value = raw.strip()
    if value[:1] in ("{", "[") or value in ("true", "false", "null") or re.fullmatch(
        r"-?\d+(\.\d+)?", value
    ):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def _parse_tool_call_body(body: str) -> list[tuple[str, dict[str, Any]]]:
    """``<tool_call>`` 内側 1 件分を (name, args) のリストへ。"""
    stripped = body.strip()
    found: list[tuple[str, dict[str, Any]]] = []
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and isinstance(obj.get("name"), str):
            args = obj.get("arguments", obj.get("parameters", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            found.append((obj["name"], args if isinstance(args, dict) else {}))
        return found
    for fm in _XML_FUNCTION_RE.finditer(stripped):
        args = {
            pm.group(1).strip(): _coerce_param_value(pm.group(2))
            for pm in _XML_PARAM_RE.finditer(fm.group(2))
        }
        found.append((fm.group(1).strip(), args))
    return found


def _parse_text_tool_calls(
    content: str, tool_names: list[str], *, step: int = 0
) -> tuple[str, list[dict[str, Any]]]:
    """content 内のテキスト形式ツール呼び出し (Qwen XML / Hermes JSON) を抽出する。

    戻り値は (ツール呼び出し部分を除いた残りテキスト, OpenAI 形式の tool_calls)。
    """
    if not content or "<tool_call>" not in content.lower():
        return content, []
    allowed = set(tool_names)
    calls: list[dict[str, Any]] = []
    for m in _TOOL_CALL_RE.finditer(content):
        for name, args in _parse_tool_call_body(m.group(1)):
            if name not in allowed:
                continue
            calls.append(
                {
                    "id": f"text_call_{step}_{len(calls)}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                }
            )
    remaining = _TOOL_CALL_RE.sub("", content).strip()
    return remaining, calls


def _env_tool_mode() -> ToolMode:
    raw = (os.environ.get("SOLOMON_RAG_TOOL_MODE") or "auto").strip().lower()
    if raw in ("auto", "native", "json"):
        return raw  # type: ignore[return-value]
    return "auto"


def _graph_schema_path() -> Path:
    raw = os.environ.get("SOLOMON_GRAPH_SCHEMA_FILE", "semantic/graph/schema.yaml")
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    return Path.cwd().resolve() / p


def _load_graph_schema_text() -> str:
    path = _graph_schema_path()
    if path.is_file():
        try:
            with path.open("r", encoding="utf-8") as fh:
                doc = yaml.safe_load(fh)
            if doc:
                return yaml.dump(doc, allow_unicode=True, sort_keys=False)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("rag_agent.schema_file_failed", path=str(path), error=str(exc))

    try:
        from solomon.graph.browse import fetch_schema

        schema = fetch_schema()
        return (
            "（スキーマファイルが無いため db.labels 等の一覧のみ）\n"
            f"node_labels: {schema.node_labels}\n"
            f"relationship_types: {schema.relationship_types}\n"
            f"property_keys: {schema.property_keys[:80]}\n"
        )
    except Exception as exc:  # noqa: BLE001
        _logger.debug("rag_agent.fetch_schema_failed", error=str(exc))
        return "（グラフスキーマ情報を取得できませんでした）"


_TABLE_SCHEMA_MAX_CHARS = 12000


def _table_schema_section(question: str, user_ctx: UserContext | None) -> str:
    """sql_query 用のスキーマ（列・結合キー・検証済みクエリ例）。

    テーブル名だけでは agent が SQL を書けず、自然言語 → SQL の二重生成に頼ることになるため、
    Text2SQL と同じスキーマ文脈を渡す。Trino 未設定時は名前だけのカタログに落とす。
    """
    from solomon.semantic.context import render_table_catalog
    from solomon.tools.schema_context import build_schema_context

    trino_cfg = get_trino_config()
    if trino_cfg is not None:
        try:
            block = build_schema_context(
                question,
                catalog=trino_cfg.catalog,
                schema=trino_cfg.schema,
                user_ctx=user_ctx,
                max_chars=_TABLE_SCHEMA_MAX_CHARS,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("rag_agent.schema_context_failed", error=str(exc))
            block = ""
        if "\n### " in f"\n{block}":
            return "## テーブルスキーマ（sql_query 用）\n" + block
    return render_table_catalog(max_chars=6000)


def _semantic_sections_for_sources(
    enabled_sources: frozenset[str],
    *,
    question: str = "",
    user_ctx: UserContext | None = None,
) -> list[str]:
    """Ossie 集約コンテキストとソースカタログ（有効ソースのみ）。"""
    from solomon.semantic.context import (
        render_business_context,
        render_document_catalog,
        render_graph_schema,
        render_tool_hints,
    )
    from solomon.semantic.source_catalog import build_source_catalog

    sections: list[str] = []
    hints = render_tool_hints()
    if hints.strip():
        sections.append(hints)
    biz = render_business_context(max_chars=4000)
    if biz.strip():
        sections.append(biz)

    catalog = build_source_catalog(sources=set(enabled_sources), force=True)
    if catalog.warnings:
        sections.append(
            "## 接続警告\n"
            + "\n".join(f"- {w}" for w in catalog.warnings[:8])
        )

    if "table" in enabled_sources:
        sections.append(_table_schema_section(question, user_ctx))
    if "graph" in enabled_sources:
        labels = catalog.graph.get("ossie_labels") or []
        if labels:
            sections.append("## グラフ (Ossie)\n" + ", ".join(str(x) for x in labels))
        sections.append(render_graph_schema(max_chars=4000))
        sections.append("## グラフ実行スキーマ\n" + _load_graph_schema_text())
    if "search" in enabled_sources:
        sections.append(render_document_catalog(max_chars=4000))
    return sections


def build_system_prompt(
    *,
    enabled_sources: frozenset[str],
    disabled_sources: list[str],
    tool_names: list[str],
    has_history: bool = False,
    question: str = "",
    user_ctx: UserContext | None = None,
) -> str:
    """``question`` は検証済みクエリ例の選択、``user_ctx`` はスキーマ取得の認可に使う。"""
    sections: list[str] = [
        "あなたはテーブル・グラフ・文書検索を横断する調査アシスタントです。"
        "質問に答えるために必要な事実を、このセッションで有効なツールだけで集めてください。\n",
        "## このセッションで使えるツール\n"
        + (", ".join(tool_names) if tool_names else "（なし — 回答は限定的）")
        + "\n",
    ]
    if disabled_sources:
        sections.append(
            "## 無効なソース（このセッションでは利用不可）\n"
            + ", ".join(disabled_sources)
            + "\n"
            "無効なソースが無いと確定できない事項は「このソース構成では特定できない」と書き、"
            "推測で埋めないこと。\n"
        )

    tool_help: list[str] = []
    if "sql_query" in tool_names:
        tool_help.append("- 構造化された数値・一覧・集計: sql_query")
    if "graph_query" in tool_names:
        tool_help.append("- つながり・多段の追跡・系譜: graph_query")
    if "doc_search" in tool_names:
        tool_help.append(
            "- 自由記述の文書（理由・経緯・過去事例）: doc_search"
            "（内部で言い換えも検索するので、同じ目的で言い換えて繰り返さない）"
        )
    if tool_help:
        sections.append("## ツールの使い分け\n" + "\n".join(tool_help) + "\n")

    if "sql_query" in tool_names:
        sections.append(
            "## 件数・一覧・集計を含む質問（sql_query）\n"
            "- sql_query には sql を書いて渡す。テーブル名・列名・結合キーは"
            "「テーブルスキーマ」にあるものだけを使う。"
            "似た質問の検証済みクエリ例があれば、それを今回の条件に合わせて直して使う。\n"
            "- 条件に使う列の値の表記（コード値・区分名など）が分からないときは、"
            "先に `SELECT DISTINCT 列 … LIMIT` で確かめてから WHERE に書く。\n"
            "- 質問に件数（「N 件」など）・「すべて」・内訳を求める語があるときは、"
            "LIMIT 付きのサンプル行から推測しない。"
            "質問の条件（対象・種別・症状・期間など）をすべて WHERE に入れ、"
            "COUNT / GROUP BY で全件を集計する。\n"
            "- 列名や値の表記が分からないときだけ、先に少数のサンプル行で確認し、"
            "その後に必ず集計クエリを実行する。\n"
            "- 集計した合計件数を質問の件数と照合する。一致すれば内訳（グループごとの件数）を結論に書く。"
            "一致しなければ条件を見直して再実行し、それでも合わないときは差と考えられる理由を未確定事項に書く。\n"
            "- 複数テーブルにまたがる条件は JOIN でまとめてよい。\n"
        )

    if "graph_query" in tool_names:
        sections.append(
            "## つながり・上流/下流・影響範囲の追跡（graph_query）\n"
            "- 段数が決まっていない追跡は、固定段数の JOIN ではなく graph_query の"
            "可変長パス（例: `-[:REL*1..8]->`）で 1 回でたどる。"
            "上流へたどるときは辺を逆向き（`<-[:REL*1..8]-`）に書く。\n"
            "- 「他にどこに使われたか」「影響を受けるのはどれか」という質問は、"
            "(1) 与えられた対象から上流へたどって共通の起点を特定し、"
            "(2) その起点から下流へたどって全件を列挙・集計する、の 2 段で進める。\n"
            "- 起点の ID が分からないときは、sql_query / doc_search で先に特定してから graph_query に渡す。"
            "ID は文字列リテラルではなく params で渡す。\n"
            "- グラフ定義のクエリ例があれば、ラベル名・辺の向き・プロパティ名をそれに合わせる。\n"
        )
    elif "sql_query" in tool_names:
        sections.append(
            "## つながり・上流/下流の追跡（グラフ無効時）\n"
            "- 親子関係の表をたどるときは段数を決め打ちしない。"
            "WITH RECURSIVE が使えればそれを使い、使えなければ新しい行が出なくなるまで"
            "1 段ずつ sql_query を繰り返す。\n"
        )

    if has_history:
        sections.append(
            "## 会話の続き\n"
            "- このメッセージの前にある user / assistant の発言は、同じセッションの直前のやり取り。\n"
            "- 今回の質問に「その」「それ」「上記」「先ほどの」などがあれば、"
            "直前の回答に出た ID・値・対象を指すものとして解釈し、ツールの条件に使う。\n"
            "- 直前の回答の値は出発点として使ってよいが、"
            "今回の結論に使う事実はこのターンのツール結果で確かめる。\n"
        )

    sections.append(
        "## 調査の進め方\n"
        "- 1 つのツールの結果を次のツールの条件（ID・キーワード）に使ってよい。\n"
        "- 表記ゆれ（設備名の略称など）は文書と表を突き合わせて同一視してよいが、"
        "そう判断した根拠を最終回答に書くこと。\n"
        "- 質問の対象（品目名・名称）は、文書の似た語で推測せず、表やグラフで ID を特定してから使う。\n"
        "- 「〜を調べるには X が必要」と書く前に、X がこのセッションで使えるなら実行する。"
        "未確定事項に書いてよいのは、使えるツールで確かめようとして確かめられなかったことだけ。\n"
        "- ツール結果に無い数値や ID を作らない。プレースホルダ（XXX など）の値を書かない。\n"
        "- 根拠には結論を直接支えるツール結果だけを挙げ、関係の薄い検索ヒットは挙げない。\n\n"
        "根拠の引用: 文書を根拠にするときは `〔doc:<doc_id>〕`、"
        "グラフ結果を根拠にするときは `〔graph:<n>〕` "
        "（n はこのセッションで**成功した** graph_query の通し番号、1 から）と本文中に書く。\n\n"
        "## 最終回答の形式（日本語 Markdown）\n"
        "1. 結論\n"
        "2. 根拠（使ったツール名と参照した ID / キー）\n"
        "3. 未確定事項\n"
    )

    for block in _semantic_sections_for_sources(
        enabled_sources, question=question, user_ctx=user_ctx
    ):
        if block.strip():
            sections.append(block.strip() + "\n")

    return "\n".join(sections)


def _truncate_tool_result(payload: dict[str, Any]) -> tuple[str, bool]:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= _RESULT_MAX_CHARS:
        return text, False
    trimmed = text[: _RESULT_MAX_CHARS - 80] + "…"
    return trimmed + '\n"(truncated: tool result exceeded 6000 characters)"', True


def _hit_from_tool(name: str, result: dict[str, Any]) -> SourceHit | None:
    if result.get("status") != "ok":
        return None
    if name == "graph_query":
        return SourceHit(
            source="graph",
            kind="cypher",
            payload={
                "records": result.get("records"),
                "count": result.get("count"),
                "cypher": result.get("cypher"),
                "params": result.get("params"),
            },
        )
    if name == "sql_query":
        return SourceHit(
            source="lakehouse",
            kind="sql",
            payload={
                "sql": result.get("sql"),
                "columns": result.get("columns"),
                "rows": result.get("rows"),
                "row_count": result.get("row_count"),
            },
        )
    if name == "doc_search":
        return SourceHit(
            source="opensearch",
            kind="document",
            score=None,
            payload={
                "documents": result.get("documents"),
                "query": result.get("query"),
                "count": result.get("count"),
            },
        )
    return None


def _tool_count(result: dict[str, Any]) -> int:
    if result.get("status") != "ok":
        return 0
    if "count" in result:
        try:
            return int(result["count"])
        except (TypeError, ValueError):
            pass
    if "row_count" in result:
        try:
            return int(result["row_count"])
        except (TypeError, ValueError):
            pass
    docs = result.get("documents")
    if isinstance(docs, list):
        return len(docs)
    recs = result.get("records")
    if isinstance(recs, list):
        return len(recs)
    return 0


def _litellm_completion(**kwargs: Any) -> Any:
    import litellm  # type: ignore

    return litellm.completion(**kwargs)


def _is_tools_unsupported(exc: Exception) -> bool:
    name = type(exc).__name__
    if name in ("BadRequestError", "InvalidRequestError", "UnsupportedParamsError"):
        return True
    msg = str(exc).lower()
    return "tool" in msg and ("unsupported" in msg or "invalid" in msg)


def _merge_completion_kwargs(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    tool_choice: str | None,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> dict[str, Any] | None:
    built = _text_completion_kwargs(
        messages,  # type: ignore[arg-type]
        agent_key="rag_agent",
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    if built is None:
        return None
    kwargs, _provider = built
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    return kwargs


def _message_from_response(resp: Any) -> dict[str, Any]:
    return resp["choices"][0]["message"]  # type: ignore[index]


def _run_tool(
    tools_by_name: dict[str, AgentTool],
    cache: dict[str, dict[str, Any]],
    name: str,
    args: dict[str, Any],
    *,
    on_event: EventCallback | None,
) -> tuple[dict[str, Any], bool, float]:
    tool = tools_by_name.get(name)
    if tool is None:
        result = {"status": "error", "message": f"Unknown tool: {name}"}
        return result, False, 0.0

    key = cache_key(name, args)
    if key in cache:
        if on_event:
            on_event({"type": "tool_end", "name": name, "cached": True, "ok": True})
        return cache[key], True, 0.0

    if on_event:
        start_ev: dict[str, Any] = {"type": "tool_start", "name": name, "args": args}
        if name == "doc_search":
            q = str(args.get("query") or "").strip()
            if q:
                start_ev["query"] = q
                try:
                    from solomon.opensearch.query_expansion import (
                        doc_search_expansion_enabled,
                        expand_query,
                    )

                    if doc_search_expansion_enabled():
                        expanded = expand_query(q)
                        if expanded:
                            start_ev["expanded_queries"] = expanded
                except Exception as exc:  # noqa: BLE001
                    _logger.debug("rag_agent.doc_expand_preview_failed", error=str(exc))
        on_event(start_ev)

    t0 = time.perf_counter()
    try:
        result = tool.execute(args)
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "message": str(exc)}
    elapsed = time.perf_counter() - t0
    ok = result.get("status") == "ok"
    cache[key] = result

    if on_event:
        end_ev: dict[str, Any] = {
            "type": "tool_end",
            "name": name,
            "ok": ok,
            "duration_ms": int(elapsed * 1000),
            "count": _tool_count(result),
        }
        if isinstance(result.get("expanded_queries"), list):
            end_ev["expanded_queries"] = result["expanded_queries"]
        if result.get("query"):
            end_ev["query"] = result["query"]
        on_event(end_ev)
    return result, False, elapsed


def _json_turn(
    messages: list[dict[str, Any]],
    tool_names: list[str],
    *,
    max_tokens: int,
    temperature: float,
    timeout: float,
    retry: bool,
) -> tuple[dict[str, Any] | None, bool]:
    """JSON モード 1 ターン。戻り値 (parsed, need_retry)."""
    sys = messages[0]["content"]
    if _JSON_SYSTEM_TAIL.format(tool_names=", ".join(tool_names)) not in sys:
        messages[0] = {
            "role": "system",
            "content": sys + "\n\n" + _JSON_SYSTEM_TAIL.format(tool_names=", ".join(tool_names)),
        }

    kwargs = _merge_completion_kwargs(
        messages,
        tools=None,
        tool_choice=None,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    if kwargs is None:
        return None, False

    try:
        resp = _litellm_completion(**kwargs)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("rag_agent.json_completion_failed", error=str(exc))
        return None, False

    msg = _message_from_response(resp)
    content = msg.get("content")
    parsed = _parse_json_lenient(content)
    if parsed is None and not retry:
        return None, True
    return parsed, False


def _native_turn(
    messages: list[dict[str, Any]],
    openai_tools: list[dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    timeout: float,
    tool_choice: str = "auto",
) -> dict[str, Any] | None:
    kwargs = _merge_completion_kwargs(
        messages,
        tools=openai_tools,
        tool_choice=tool_choice,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    if kwargs is None:
        return None
    resp = _litellm_completion(**kwargs)
    return _message_from_response(resp)


def run_knowledge_agent(
    prompt: str,
    *,
    user_ctx: UserContext,
    tools: list[AgentTool] | None = None,
    enabled_sources: frozenset[str] | None = None,
    disabled_sources: list[str] | None = None,
    on_event: EventCallback | None = None,
    max_steps: int = 8,
    timeout_sec: float = 150.0,
    history: list[tuple[str, str]] | None = None,
) -> KnowledgeRagResult:
    """ツール呼び出し型 Knowledge RAG（最大 ``max_steps`` 手）。

    ``history`` は同じセッションの直前の (質問, 回答)。指示語つきの続き質問を解決するために使う。
    """
    if get_llm_agent_config("rag_agent") is None:
        raise RuntimeError("rag_agent LLM is not configured")

    if enabled_sources is None:
        enabled_sources = frozenset({"table", "graph", "search"})
    if disabled_sources is None:
        disabled_sources = []

    agent_tools = (
        tools
        if tools is not None
        else default_agent_tools(user_ctx, enabled_sources)
    )
    tools_by_name = {t.name: t for t in agent_tools}
    openai_tools = [t.to_openai_tool() for t in agent_tools]
    tool_names = [t.name for t in agent_tools]

    prior = _history_messages(history)
    system = build_system_prompt(
        enabled_sources=enabled_sources,
        disabled_sources=disabled_sources,
        tool_names=tool_names,
        has_history=bool(prior),
        question=prompt,
        user_ctx=user_ctx,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        *prior,
        {"role": "user", "content": prompt},
    ]

    mode = _env_tool_mode()
    use_json = mode == "json"
    if mode == "auto":
        use_json = False

    hits: list[SourceHit] = []
    tool_calls_log: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}
    final_answer = ""
    steps_taken = 0
    deadline = time.monotonic() + timeout_sec
    json_retry_pending = False

    while steps_taken < max_steps and time.monotonic() < deadline:
        steps_taken += 1
        try:
            if use_json:
                parsed, need_retry = _json_turn(
                    messages,
                    tool_names,
                    max_tokens=2048,
                    temperature=0.2,
                    timeout=min(60.0, timeout_sec),
                    retry=json_retry_pending,
                )
                json_retry_pending = False
                if parsed is None and need_retry:
                    messages.append(
                        {
                            "role": "user",
                            "content": "前の応答は有効な JSON ではありませんでした。"
                            "指定形式の JSON のみを返してください。",
                        }
                    )
                    json_retry_pending = True
                    steps_taken -= 1
                    continue
                if not parsed:
                    break

                thought = parsed.get("thought")
                if isinstance(thought, str) and thought.strip() and on_event:
                    on_event({"type": "thought", "text": thought.strip()[:500]})

                if isinstance(parsed.get("final_answer"), str):
                    final_answer = str(parsed["final_answer"]).strip()
                    break

                action = parsed.get("action")
                args = parsed.get("args")
                if not isinstance(action, str) or not isinstance(args, dict):
                    break

                result, cached, elapsed = _run_tool(
                    tools_by_name, cache, action, args, on_event=on_event
                )
                tool_calls_log.append(
                    {
                        "name": action,
                        "args": args,
                        "ok": result.get("status") == "ok",
                        "duration_ms": int(elapsed * 1000),
                        "count": _tool_count(result),
                        "cached": cached,
                    }
                )
                hit = _hit_from_tool(action, result)
                if hit:
                    hits.append(hit)

                result_text, _ = _truncate_tool_result(result)
                messages.append(
                    {"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)}
                )
                messages.append(
                    {"role": "user", "content": f"Tool {action} result:\n{result_text}"}
                )
                continue

            # native
            try:
                msg = _native_turn(
                    messages,
                    openai_tools,
                    max_tokens=2048,
                    temperature=0.2,
                    timeout=min(60.0, timeout_sec),
                )
            except Exception as exc:  # noqa: BLE001
                if mode == "auto" and _is_tools_unsupported(exc):
                    _logger.info("rag_agent.fallback_to_json", error=str(exc))
                    use_json = True
                    steps_taken -= 1
                    continue
                _logger.warning("rag_agent.native_failed", error=str(exc))
                break

            if msg is None:
                break

            tool_calls = msg.get("tool_calls") or []
            content = _strip_reasoning(msg.get("content"))
            if not tool_calls:
                remaining, text_calls = _parse_text_tool_calls(
                    content, tool_names, step=steps_taken
                )
                if text_calls:
                    _logger.info(
                        "rag_agent.text_tool_calls_parsed",
                        count=len(text_calls),
                        names=[c["function"]["name"] for c in text_calls],
                    )
                    tool_calls = text_calls
                    content = remaining
                    msg = {
                        "role": "assistant",
                        "content": remaining or None,
                        "tool_calls": text_calls,
                    }
            if content and on_event:
                on_event({"type": "thought", "text": content[:500]})

            if tool_calls:
                messages.append(msg)
                for tc in tool_calls:
                    fn = tc.get("function") or {}
                    name = fn.get("name")
                    raw_args = fn.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        args = {}
                    if not isinstance(args, dict):
                        args = {}
                    if not isinstance(name, str):
                        continue

                    result, cached, elapsed = _run_tool(
                        tools_by_name, cache, name, args, on_event=on_event
                    )
                    tool_calls_log.append(
                        {
                            "name": name,
                            "args": args,
                            "ok": result.get("status") == "ok",
                            "duration_ms": int(elapsed * 1000),
                            "count": _tool_count(result),
                            "cached": cached,
                        }
                    )
                    hit = _hit_from_tool(name, result)
                    if hit:
                        hits.append(hit)

                    result_text, _ = _truncate_tool_result(result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.get("id") or name,
                            "content": result_text,
                        }
                    )
                continue

            if content:
                final_answer = content
                break

        except Exception as exc:  # noqa: BLE001
            _logger.warning("rag_agent.step_failed", error=str(exc), step=steps_taken)
            break

    if not final_answer:
        messages.append(
            {
                "role": "user",
                "content": (
                    "最大手数に達しました。ここまでに得たツール結果だけを根拠に、"
                    "日本語 Markdown で最終回答を書いてください。"
                    + (
                        ' JSON 形式なら {"final_answer": "..."} のみ。'
                        if use_json
                        else ""
                    )
                ),
            }
        )
        # まとめの 1 手は思考 + 長めの Markdown になるので、通常手より token を多く取る
        if use_json:
            parsed, _ = _json_turn(
                messages,
                tool_names,
                max_tokens=_FINAL_TURN_MAX_TOKENS,
                temperature=0.2,
                timeout=min(90.0, timeout_sec),
                retry=False,
            )
            if parsed and isinstance(parsed.get("final_answer"), str):
                final_answer = str(parsed["final_answer"]).strip()
        else:
            try:
                msg = _native_turn(
                    messages,
                    openai_tools,
                    max_tokens=_FINAL_TURN_MAX_TOKENS,
                    temperature=0.2,
                    timeout=min(90.0, timeout_sec),
                    tool_choice="none",
                )
                raw = msg.get("content") if msg else None
                if isinstance(raw, str):
                    remaining, _ = _parse_text_tool_calls(
                        _strip_reasoning(raw), tool_names
                    )
                    final_answer = remaining
                if not final_answer:
                    _logger.warning(
                        "rag_agent.final_turn_empty",
                        content_chars=len(raw) if isinstance(raw, str) else 0,
                        has_tool_calls=bool(msg and msg.get("tool_calls")),
                    )
            except Exception as exc:  # noqa: BLE001
                _logger.warning("rag_agent.final_turn_failed", error=str(exc))

    if not final_answer:
        final_answer = (
            "## 結論\n"
            "十分な情報を取得できませんでした。\n\n"
            "## 未確定事項\n"
            "- LLM またはツールの応答が不完全でした。"
        )

    # 最後に成功した SQL（探索のあとの集計クエリが回答の主根拠になりやすい）
    sql_executed = None
    for h in reversed(hits):
        if h.source == "lakehouse":
            sql_executed = h.payload.get("sql")
            break

    plan = RetrievalPlan(
        strategy="AGENT",
        query=prompt,
        confidence=1.0,
        reasoning=f"tool_calls={len(tool_calls_log)} steps={steps_taken}",
    )
    bundle = RetrievalBundle(
        plan=plan,
        hits=hits,
        disabled_sources=list(disabled_sources),
    )

    from solomon.rag.evidence import enrich_answer_with_evidence

    final_answer = enrich_answer_with_evidence(
        final_answer,
        hits=hits,
        tool_calls=tool_calls_log,
        sql_executed=sql_executed if isinstance(sql_executed, str) else None,
    )

    return KnowledgeRagResult(
        plan=plan,
        bundle=bundle,
        answer_markdown=final_answer,
        sql_executed=sql_executed if isinstance(sql_executed, str) else None,
        tool_calls=tool_calls_log,
    )


__all__ = ["run_knowledge_agent", "build_system_prompt"]
