"""J5 製造トレース (KIBAN / A/T機番) 向けデモ QA — Lakehouse + Neo4j から決定論的に回答。"""

from __future__ import annotations

import re
from typing import Any, Optional

from solomon.graph.config import get_neo4j_config
from solomon.graph.manufacturing.silver_trino import fetch_trace_summary_from_silver
from solomon.graph.neo4j_connect import iter_neo4j_connection_uris
from solomon.transport.user_context import UserContext
from solomon.rag.models import (
    KnowledgeRagResult,
    RetrievalBundle,
    RetrievalPlan,
    SourceHit,
)

_TRACE_ID_RE = re.compile(r"\b(26G(?:3V|YP)\d{5})\b", re.IGNORECASE)
_TRACE_PROMPT_MARKERS = (
    "出検",
    "完検",
    "shukken",
    "kanken",
    "顧客品番",
    "合格",
    "通過日時",
    "ダンプ",
    "メモリ",
    "アドレスマップ",
    "測定",
    "機番",
)
_PART_NO_RE = re.compile(r"\b(\d{10})\b")
_HINBAN_PROMPT_MARKERS = (
    "品番",
    "試験データ",
    "ファイル名",
    "種類",
    "載",
    "どの",
    "ヒット",
    "含",
)
_FORMAT_LABELS: dict[str, str] = {
    "vb": "VB試験 (inspection-vb)",
    "j5_main_id": "J5-メインID (inspection-j5_main_id)",
    "kanken": "J5-完検 (inspection-kanken)",
    "j5_shukken_id": "J5-出検ID (inspection-j5_shukken_id)",
}


def parse_trace_id_from_prompt(prompt: str) -> str | None:
    m = _TRACE_ID_RE.search(prompt.strip())
    return m.group(1).upper() if m else None


def is_manufacturing_trace_detail_prompt(prompt: str) -> bool:
    text = prompt.strip()
    if parse_trace_id_from_prompt(text) is None:
        return False
    lower = text.lower()
    return any(m in text or m.lower() in lower for m in _TRACE_PROMPT_MARKERS)


def parse_part_number_from_prompt(prompt: str) -> str | None:
    """品番 3061042090 形式、または文脈付き 10 桁品番を抽出する。"""
    text = prompt.strip()
    m = re.search(r"品番\s*[：:]?\s*(\d{10})\b", text)
    if m:
        return m.group(1)
    if "品番" in text or "ヒンバン" in text.upper():
        m2 = _PART_NO_RE.search(text)
        if m2:
            return m2.group(1)
    return None


def is_manufacturing_part_lookup_prompt(prompt: str) -> bool:
    """品番横断検索（試験種別・ファイル名）向けデモ QA。"""
    text = prompt.strip()
    if parse_part_number_from_prompt(text) is None:
        return False
    if parse_trace_id_from_prompt(text) is not None and is_manufacturing_trace_detail_prompt(text):
        return False
    return any(m in text for m in _HINBAN_PROMPT_MARKERS)


def _format_label(fmt: str | None) -> str:
    if not fmt:
        return "—"
    return _FORMAT_LABELS.get(fmt, fmt)


_TRACE_DOC_MARKERS = (
    "ドキュメント",
    "見つけ",
    "全部",
    "関連",
    "関係",
    "ファイル",
    "document",
    "find",
    "semantic",
)


def is_manufacturing_trace_documents_prompt(prompt: str) -> bool:
    """KIBAN に紐づく Bronze ファイル一覧（inspection-* 横断）。"""
    text = prompt.strip()
    if parse_trace_id_from_prompt(text) is None:
        return False
    if is_manufacturing_trace_detail_prompt(text):
        return False
    lower = text.lower()
    return any(m in text or m in lower for m in _TRACE_DOC_MARKERS)


def format_trace_documents_markdown(trace_id: str, docs: list[dict[str, Any]]) -> str:
    """KIBAN / trace_id に一致する Bronze ファイル一覧。"""
    lines = [
        f"**{trace_id}**（KIBAN）に関連する試験データ（OpenSearch `inspection-*`）",
        "",
        "| 種類 | ファイル名 | 品番 (payload) | object_key |",
        "|------|------------|----------------|------------|",
    ]
    seen_keys: set[str] = set()
    for doc in docs:
        key = str(doc.get("object_key") or doc.get("title") or "")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        title = str(doc.get("title") or key.rsplit("/", 1)[-1] or "—")
        raw_fmt = doc.get("format")
        fmt = _format_label(str(raw_fmt) if raw_fmt else None)
        payload = doc.get("payload") if isinstance(doc.get("payload"), dict) else {}
        part_bits: list[str] = []
        for field in ("hinban", "at_kiban", "customer_hinban", "kiban"):
            val = payload.get(field)
            if val not in (None, ""):
                part_bits.append(f"{field}={val}")
        part_col = " · ".join(part_bits) if part_bits else "—"
        obj = key or "—"
        lines.append(f"| {fmt} | {title} | {part_col} | `{obj}` |")
    if not seen_keys:
        lines.append("| — | 該当なし | — | — |")
    lines.extend(
        [
            "",
            "_Semantic Search タブと同じ `inspection-*` インデックス。"
            " ファイル名を覚えていなくても trace_id / 平坦化メタで入口を作れます。_",
        ]
    )
    return "\n".join(lines)


_VB_PATH_KNOWN_TOKENS = ("VB_圧無", "圧無", "蘇州")
_VB_PATH_PROMPT_MARKERS = (
    "フォルダ",
    "object_key",
    "試験ファイル",
    "パス",
    "階層",
    "ある？",
    "あります",
)


def parse_vb_path_terms(prompt: str) -> list[str]:
    """プロンプト内の VB 試験パス断片（デモ: 圧無 / 蘇州 / VB_圧無 等）。"""
    text = prompt.strip()
    terms: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        t = raw.strip().strip("「」『』\"'")
        if len(t) < 2 or t in seen:
            return
        seen.add(t)
        terms.append(t)

    for tok in _VB_PATH_KNOWN_TOKENS:
        if tok in text:
            add(tok)
    for m in re.finditer(r"VB[_\w\u4e00-\u9fff]+", text):
        add(m.group(0))
    for m in re.finditer(r"([^\sや、?？]+)\s*みたいな", text):
        add(m.group(1))
    return terms


def is_vb_path_lookup_prompt(prompt: str) -> bool:
    """VB 試験の S3/OS パス（object_key）探索デモ QA。"""
    text = prompt.strip()
    is_vb = bool(
        re.search(r"\bVB\b", text, re.IGNORECASE)
        or "VB_" in text
        or "ＶＢ" in text
    )
    if not is_vb:
        return False
    if parse_vb_path_terms(text):
        return True
    return any(m in text for m in _VB_PATH_PROMPT_MARKERS) and (
        "圧無" in text or "蘇州" in text
    )


_TRACE_GRAPH_MARKERS = (
    "グラフ",
    "ソースファイル",
    "トレース",
    "関係",
    "説明",
    "Cypher",
    "Product",
    "Kiban",
    "HAS_KIBAN",
    "INGESTED_INTO",
    "製品",
)

_GRAPH_CYPHER = """
MATCH (k:Kiban {id: $trace_id})<-[:HAS_KIBAN]-(p:Product)<-[:INGESTED_INTO]-(f:SourceFile)
RETURN f.key AS key, f.format AS format, p.trace_id AS product_trace_id
ORDER BY f.format, f.key
""".strip()


def is_manufacturing_trace_graph_prompt(prompt: str) -> bool:
    """製品トレースと SourceFile / Kiban のグラフ関係説明（デモ Q4）。"""
    text = prompt.strip()
    if parse_trace_id_from_prompt(text) is None:
        return False
    if is_manufacturing_trace_detail_prompt(text):
        return False
    lower = text.lower()
    return any(m in text or m.lower() in lower for m in _TRACE_GRAPH_MARKERS)


def fetch_trace_graph_context(
    trace_id: str,
    *,
    user_ctx: UserContext | None = None,
) -> dict[str, Any]:
    """Neo4j Bronze → Iceberg ingest_file_state → OpenSearch の順でファイル関係を集める。"""
    from solomon.graph.manufacturing.neo4j_bronze import fetch_bronze_graph_context
    from solomon.graph.manufacturing.silver_trino import (
        fetch_ingest_files_for_trace,
        silver_schema_name,
    )
    from solomon.opensearch.inspection_indices import search_documents_by_trace_id

    bronze = fetch_bronze_graph_context(trace_id)
    if not bronze.get("error"):
        return bronze

    ice_files = fetch_ingest_files_for_trace(trace_id, user_ctx)
    if ice_files:
        return {
            "trace_id": trace_id,
            "source": "lakehouse",
            "model": "ingest_file_state",
            "ingest_files": ice_files,
            "notes": (
                f"Iceberg `{silver_schema_name()}.ingest_file_state` から "
                f"{len(ice_files)} 件（Neo4j 未投入時のフォールバック）。"
            ),
        }

    docs = search_documents_by_trace_id(trace_id, size=50)
    if docs:
        return {
            "trace_id": trace_id,
            "source": "opensearch",
            "model": "inspection",
            "opensearch_docs": docs,
            "notes": "OpenSearch inspection-*（Neo4j / ingest_file_state 不在時）。",
        }

    return bronze


def format_trace_graph_markdown(trace_id: str, ctx: dict[str, Any]) -> str:
    model = ctx.get("model") or "bronze"
    lines = [
        f"**{trace_id}** の製品トレース — ソースファイルと KIBAN の関係",
        "",
        "```mermaid",
        "graph LR",
        "  SF[SourceFile]",
        "  P[Product]",
        "  K[Kiban]",
        "  SF -->|INGESTED_INTO| P",
        "  P -->|HAS_KIBAN| K",
        "```",
        "",
        "参照 Cypher（Neo4j Bronze モデル）:",
        "",
        f"```cypher\n{_GRAPH_CYPHER}\n```",
        "",
        f"（データソース: **{model}** / {ctx.get('source', '—')}）",
        "",
    ]
    if ctx.get("notes"):
        lines.append(f"_{ctx['notes']}_")
        lines.append("")

    neo_files = ctx.get("neo4j_source_files")
    if isinstance(neo_files, list) and neo_files:
        lines.extend(
            [
                "| format | object_key (SourceFile.key) | product_trace_id |",
                "|--------|---------------------------|------------------|",
            ]
        )
        for row in neo_files:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"| {row.get('format') or '—'} | `{row.get('key') or '—'}` | "
                f"{row.get('product_trace_id') or trace_id} |"
            )
        vb = ctx.get("neo4j_vb_links")
        if isinstance(vb, list) and vb:
            lines.append("")
            lines.append("**Kiban → VbMachine (TESTED_ON_VB)**")
            for link in vb[:5]:
                if isinstance(link, dict):
                    lines.append(
                        f"- VB `{link.get('vb_machine_no')}` "
                        f"({link.get('link_type') or 'link'}, confidence={link.get('confidence')})"
                    )
        return "\n".join(lines)

    ice_files = ctx.get("ingest_files")
    if isinstance(ice_files, list) and ice_files:
        lines.extend(
            [
                "| format | object_key | vb_machine_no |",
                "|--------|------------|---------------|",
            ]
        )
        for row in ice_files:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"| {row.get('format') or '—'} | `{row.get('object_key') or '—'}` | "
                f"{row.get('vb_machine_no') or '—'} |"
            )
        return "\n".join(lines)

    docs = ctx.get("opensearch_docs")
    if isinstance(docs, list) and docs:
        lines.extend(
            [
                "| format | ファイル名 | object_key |",
                "|--------|------------|------------|",
            ]
        )
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            lines.append(
                f"| {doc.get('format') or '—'} | {doc.get('title') or '—'} | "
                f"`{doc.get('object_key') or '—'}` |"
            )
        return "\n".join(lines)

    lines.append("該当するソースファイルが見つかりませんでした。")
    return "\n".join(lines)


def format_vb_path_lookup_markdown(terms: list[str], docs: list[dict[str, Any]]) -> str:
    term_csv = " / ".join(terms)
    lines = [
        f"VB 試験（`inspection-vb`）で object_key に **{term_csv}** を含むファイル",
        "",
        "| ファイル名 | object_key | V/B機番 | 判定 |",
        "|------------|------------|---------|------|",
    ]
    seen: set[str] = set()
    for doc in docs:
        key = str(doc.get("object_key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        title = str(doc.get("title") or key.rsplit("/", 1)[-1])
        payload = doc.get("payload") if isinstance(doc.get("payload"), dict) else {}
        vb_no = payload.get("vb_machine_no") or "—"
        judge = payload.get("judge") or "—"
        lines.append(f"| {title} | `{key}` | {vb_no} | {judge} |")
    if not seen:
        lines.append("| — | — | — | — |")
    lines.extend(
        [
            "",
            "_Bronze の階層パスが OpenSearch の object_key に載っているため、"
            "フォルダ名だけ覚えていなくても Semantic Search + メタで入口を作れます。_",
        ]
    )
    return "\n".join(lines)


def format_part_lookup_markdown(part_number: str, docs: list[dict[str, Any]]) -> str:
    """品番が載る Bronze ファイル一覧（OpenSearch inspection-*）。"""
    lines = [
        f"品番 **{part_number}** が payload に含まれる試験データ（OpenSearch `inspection-*`）",
        "",
        "| 種類 | ファイル名 | KIBAN (trace_id) | object_key |",
        "|------|------------|------------------|------------|",
    ]
    seen_keys: set[str] = set()
    for doc in docs:
        key = str(doc.get("object_key") or doc.get("title") or "")
        if key in seen_keys:
            continue
        seen_keys.add(key)
        title = str(doc.get("title") or key.rsplit("/", 1)[-1] or "—")
        trace = str(doc.get("trace_id") or "—")
        raw_fmt = doc.get("format")
        fmt = _format_label(str(raw_fmt) if raw_fmt else None)
        obj = key or "—"
        lines.append(f"| {fmt} | {title} | {trace} | `{obj}` |")
    if len(seen_keys) == 0:
        lines.append("| — | 該当なし | — | — |")
    lines.extend(
        [
            "",
            "_根拠: CDE Bronze 取込インデックス（メインID の HINBAN / 出検の customer_hinban 等）。_",
        ]
    )
    return "\n".join(lines)


def format_trace_summary_markdown(summary: dict[str, Any]) -> str:
    """お客様デモ用の表形式 Markdown。"""
    dump_rows = summary.get("dump_row_count")
    shukken_fields = summary.get("shukken_decoded_field_count")
    kanken_rows = summary.get("kanken_measurement_rows")
    source_note = summary.get("source_note") or (
        "Iceberg inspection_silver + Neo4j"
        if summary.get("source") == "lakehouse"
        else "Neo4j グラフ + 取込メタデータ"
    )
    lines = [
        f"**{summary.get('trace_id', '')}** の出検・完検サマリー（{source_note}）",
        "",
        "| 項目 | 目安 |",
        "|------|------|",
        f"| 顧客品番 | {summary.get('customer_part_no') or '—'} |",
        f"| 合格日時 | {summary.get('pass_datetime') or '—'} |",
        f"| ID ダンプ行数 | {dump_rows if dump_rows is not None else '—'} |",
    ]
    if shukken_fields is not None:
        lines.append(f"| 出検帯の展開項目 | 約 {shukken_fields} 件 |")
    else:
        lines.append("| 出検帯の展開項目 | — |")
    if kanken_rows is not None:
        lines.append(
            f"| 完検測定行 | {kanken_rows} 行（該当完検ファイルに基づく） |"
        )
    else:
        lines.append("| 完検測定行 | —（同一機番の完検未取込の可能性） |")
    lines.append("")
    if summary.get("notes"):
        lines.append(f"_{summary['notes']}_")
    return "\n".join(lines)


def _merge_trace_summaries(
    silver: dict[str, Any] | None,
    neo4j: dict[str, Any] | None,
    trace_id: str,
) -> dict[str, Any]:
    if silver and silver.get("error") == "NOT_FOUND":
        silver = None
    if neo4j and neo4j.get("error") == "NOT_FOUND":
        neo4j = None
    out: dict[str, Any] = {"trace_id": trace_id}
    if silver and not silver.get("error"):
        out.update({k: v for k, v in silver.items() if v is not None and k != "error"})
        out["source"] = silver.get("source", "lakehouse")
    if neo4j and not neo4j.get("error"):
        for key in (
            "customer_part_no",
            "pass_datetime",
            "dump_row_count",
            "shukken_decoded_field_count",
            "kanken_measurement_rows",
        ):
            if out.get(key) is None and neo4j.get(key) is not None:
                out[key] = neo4j[key]
        if neo4j.get("notes"):
            out["notes"] = (
                neo4j["notes"]
                if not out.get("notes")
                else f"{out['notes']} {neo4j['notes']}"
            )
        if neo4j.get("neo4j_source_files"):
            out["neo4j_source_files"] = neo4j["neo4j_source_files"]
        if out.get("source") != "lakehouse":
            out["source"] = "neo4j"
        else:
            out["source_note"] = "Iceberg inspection_silver（数値）+ Neo4j（ファイル関係）"
    if any(
        out.get(k) is not None
        for k in (
            "customer_part_no",
            "dump_row_count",
            "shukken_decoded_field_count",
            "kanken_measurement_rows",
        )
    ):
        return out
    if silver and silver.get("error") == "NOT_FOUND" and (not neo4j or neo4j.get("error")):
        return {"trace_id": trace_id, "error": "NOT_FOUND"}
    err = (silver or {}).get("error") or (neo4j or {}).get("error")
    if err:
        return {"trace_id": trace_id, "error": err}
    return {"trace_id": trace_id, "error": "NOT_FOUND"}


def fetch_trace_summary_neo4j(trace_id: str) -> dict[str, Any]:
    """Neo4j: Spark Bronze モデル (Product/Kiban) を優先、Solomon 旧モデルはフォールバック。"""
    from solomon.graph.manufacturing.neo4j_bronze import fetch_bronze_graph_context

    bronze = fetch_bronze_graph_context(trace_id)
    if bronze.get("error") == "NEO4J_NOT_CONFIGURED":
        return bronze
    if not bronze.get("error"):
        return bronze
    return _fetch_trace_summary_neo4j_legacy(trace_id)


def _fetch_trace_summary_neo4j_legacy(trace_id: str) -> dict[str, Any]:
    """Solomon Ingestion Crew 投入モデル (AssemblyUnit / MemoryDump / TestRecord)。"""
    config = get_neo4j_config()
    if config is None:
        return {"trace_id": trace_id, "error": "NEO4J_NOT_CONFIGURED"}

    unit_id = f"unit:{trace_id}"
    board_id = f"board:{trace_id}"

    cypher_shukken = """
    MATCH (u:AssemblyUnit {id: $unit_id})
    OPTIONAL MATCH (u)-[:HAS_DUMP]->(d:MemoryDump {dump_type: 'shukken_id'})
    OPTIONAL MATCH (d)-[:HAS_FIELD]->(f:DecodedField)
    RETURN u.customer_part_no AS customer_part_no,
           u.at_serial AS at_serial,
           coalesce(d.date, u.updated_at) AS pass_datetime,
           d.row_count AS dump_row_count,
           d.field_count AS dump_field_count,
           count(f) AS decoded_on_dump
    """

    cypher_kanken = """
    MATCH (b:Board {id: $board_id})-[:INSPECTED_BY]->(t:TestRecord)
    WHERE t.data_type = 'j5_kanken'
    RETURN t.row_count AS row_count,
           t.date AS kanken_date,
           t.judge AS judge
    ORDER BY t.date DESC
    LIMIT 1
    """

    try:
        from neo4j import GraphDatabase
    except ImportError:
        return {"trace_id": trace_id, "error": "neo4j driver not installed"}

    last_error: str | None = None
    for uri in iter_neo4j_connection_uris(config.uri):
        driver = GraphDatabase.driver(uri, auth=(config.username, config.password))
        try:
            driver.verify_connectivity()
            with driver.session() as session:
                shukken_row = session.run(
                    cypher_shukken, unit_id=unit_id
                ).single()
                kanken_row = session.run(
                    cypher_kanken, board_id=board_id
                ).single()
            out: dict[str, Any] = {"trace_id": trace_id}
            if shukken_row:
                out["customer_part_no"] = shukken_row.get("customer_part_no")
                out["pass_datetime"] = shukken_row.get("pass_datetime")
                dump_rows = shukken_row.get("dump_row_count")
                if dump_rows is None:
                    dump_rows = shukken_row.get("dump_field_count")
                out["dump_row_count"] = dump_rows
                decoded = shukken_row.get("decoded_on_dump")
                if decoded is not None and int(decoded) > 0:
                    out["shukken_decoded_field_count"] = int(decoded)
            if kanken_row and kanken_row.get("row_count") is not None:
                out["kanken_measurement_rows"] = int(kanken_row["row_count"])
            if not shukken_row and not kanken_row:
                out["error"] = "NOT_FOUND"
            out["model"] = "solomon_legacy"
            return out
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        finally:
            driver.close()

    return {"trace_id": trace_id, "error": last_error or "NEO4J_QUERY_FAILED"}


def _append_opensearch_footnote(out: dict[str, Any], trace_id: str) -> None:
    try:
        from solomon.opensearch.inspection_indices import (
            search_documents_by_trace_id,
            summarize_trace_documents,
        )

        docs = search_documents_by_trace_id(trace_id)
        summary = summarize_trace_documents(docs)
        if summary:
            out["notes"] = (
                f"{out['notes']} {summary}" if out.get("notes") else summary
            )
            out["opensearch_docs"] = docs
    except Exception:  # noqa: BLE001
        return


def fetch_trace_summary(
    trace_id: str,
    *,
    user_ctx: UserContext | None = None,
) -> dict[str, Any]:
    """Lakehouse (inspection_silver) を優先し、Neo4j / OpenSearch で脚注を足す。"""
    silver: dict[str, Any] | None = None
    try:
        silver = fetch_trace_summary_from_silver(trace_id, user_ctx)
    except Exception as exc:  # noqa: BLE001
        silver = {"trace_id": trace_id, "error": str(exc)}

    neo4j = fetch_trace_summary_neo4j(trace_id)
    if silver is None and neo4j.get("error") == "NEO4J_NOT_CONFIGURED":
        merged = neo4j
    else:
        merged = _merge_trace_summaries(silver, neo4j, trace_id)
    if not merged.get("error"):
        _append_opensearch_footnote(merged, trace_id)
    return merged


def try_answer_manufacturing_trace_documents_prompt(
    prompt: str,
    *,
    user_ctx: UserContext | None = None,
) -> Optional[KnowledgeRagResult]:
    """KIBAN 横断 — inspection-* 上の関連 Bronze doc 一覧。"""
    _ = user_ctx
    if not is_manufacturing_trace_documents_prompt(prompt):
        return None
    trace_id = parse_trace_id_from_prompt(prompt)
    if not trace_id:
        return None

    from solomon.opensearch.inspection_indices import search_documents_by_trace_id
    from solomon.transport.config import get_opensearch_config

    plan = RetrievalPlan(
        strategy="KEYWORD",
        query=prompt.strip(),
        confidence=0.93,
        reasoning="manufacturing trace document lookup (inspection-*)",
        entity_hint=trace_id,
    )
    if get_opensearch_config() is None:
        md = (
            f"OpenSearch が未設定です。KIBAN **{trace_id}** の検索には "
            "`inspection-*` が必要です。"
        )
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(plan=plan, hits=[], errors=[{"source": "opensearch", "message": md}]),
            answer_markdown=md,
        )

    docs = search_documents_by_trace_id(trace_id, size=50)
    if not docs:
        md = (
            f"KIBAN **{trace_id}** に一致する Bronze ドキュメントが "
            "`inspection-*` に見つかりません。CDE 取込と Search タブを確認してください。"
        )
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(
                plan=plan,
                hits=[],
                errors=[{"source": "opensearch", "message": "no hits"}],
            ),
            answer_markdown=md,
        )

    hits = [
        SourceHit(
            source="opensearch",
            kind="inspection_trace_lookup",
            payload=doc,
            score=doc.get("score"),
        )
        for doc in docs[:20]
    ]
    md = format_trace_documents_markdown(trace_id, docs)
    return KnowledgeRagResult(
        plan=plan,
        bundle=RetrievalBundle(plan=plan, hits=hits, errors=[]),
        answer_markdown=md,
    )


def try_answer_manufacturing_trace_graph_prompt(
    prompt: str,
    *,
    user_ctx: UserContext | None = None,
) -> Optional[KnowledgeRagResult]:
    """Q4: Product / Kiban / SourceFile 関係のグラフ説明。"""
    if not is_manufacturing_trace_graph_prompt(prompt):
        return None
    trace_id = parse_trace_id_from_prompt(prompt)
    if not trace_id:
        return None

    plan = RetrievalPlan(
        strategy="GRAPH_QUERY",
        query=prompt.strip(),
        confidence=0.94,
        reasoning="manufacturing trace graph (Product/Kiban/SourceFile)",
        entity_hint=trace_id,
    )

    ctx = fetch_trace_graph_context(trace_id, user_ctx=user_ctx)
    if ctx.get("error") == "NEO4J_NOT_CONFIGURED" and not ctx.get("ingest_files"):
        md = (
            "Neo4j が未設定です。`NEO4J_URI` または `NEO4J_MODE=internal` を設定してください。"
        )
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(plan=plan, hits=[], errors=[{"source": "neo4j", "message": md}]),
            answer_markdown=md,
        )

    if ctx.get("error") == "NOT_FOUND" or (
        ctx.get("error") and not ctx.get("neo4j_source_files") and not ctx.get("ingest_files")
    ):
        md = (
            f"機番 **{trace_id}** の SourceFile / Kiban 関係が "
            "Neo4j・Iceberg・OpenSearch のいずれにも見つかりません。"
        )
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(plan=plan, hits=[], errors=[{"source": "neo4j", "message": md}]),
            answer_markdown=md,
        )

    if ctx.get("error") and not (
        ctx.get("neo4j_source_files") or ctx.get("ingest_files") or ctx.get("opensearch_docs")
    ):
        md = f"参照に失敗しました: {ctx['error']}"
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(plan=plan, hits=[], errors=[{"source": "neo4j", "message": ctx["error"]}]),
            answer_markdown=md,
        )

    hit = SourceHit(
        source="neo4j" if ctx.get("model") == "bronze" else ctx.get("source", "neo4j"),  # type: ignore[arg-type]
        kind="manufacturing_trace_graph",
        payload=ctx,
    )
    md = format_trace_graph_markdown(trace_id, ctx)
    return KnowledgeRagResult(
        plan=plan,
        bundle=RetrievalBundle(plan=plan, hits=[hit], errors=[]),
        answer_markdown=md,
    )


def try_answer_vb_path_prompt(
    prompt: str,
    *,
    user_ctx: UserContext | None = None,
) -> Optional[KnowledgeRagResult]:
    """VB 試験 object_key パス探索（inspection-vb）。"""
    _ = user_ctx
    if not is_vb_path_lookup_prompt(prompt):
        return None
    terms = parse_vb_path_terms(prompt)
    if not terms:
        return None

    from solomon.opensearch.inspection_indices import search_vb_documents_by_path_terms
    from solomon.transport.config import get_opensearch_config

    plan = RetrievalPlan(
        strategy="KEYWORD",
        query=prompt.strip(),
        confidence=0.91,
        reasoning="VB path lookup on inspection-vb object_key",
        entity_hint=",".join(terms),
    )
    if get_opensearch_config() is None:
        md = "OpenSearch が未設定です。VB パス検索には `inspection-vb` が必要です。"
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(plan=plan, hits=[], errors=[{"source": "opensearch", "message": md}]),
            answer_markdown=md,
        )

    docs = search_vb_documents_by_path_terms(terms, size=50)
    if not docs:
        md = (
            f"object_key に **{' / '.join(terms)}** を含む VB 試験が "
            "`inspection-vb` に見つかりません。Search タブでパスを確認してください。"
        )
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(
                plan=plan,
                hits=[],
                errors=[{"source": "opensearch", "message": "no vb hits"}],
            ),
            answer_markdown=md,
        )

    hits = [
        SourceHit(
            source="opensearch",
            kind="inspection_vb_path_lookup",
            payload=doc,
            score=doc.get("score"),
        )
        for doc in docs[:20]
    ]
    md = format_vb_path_lookup_markdown(terms, docs)
    return KnowledgeRagResult(
        plan=plan,
        bundle=RetrievalBundle(plan=plan, hits=hits, errors=[]),
        answer_markdown=md,
    )


def try_answer_manufacturing_part_prompt(
    prompt: str,
    *,
    user_ctx: UserContext | None = None,
) -> Optional[KnowledgeRagResult]:
    """品番横断 QA — solomon-datasets ではなく inspection-* を参照する。"""
    _ = user_ctx
    if not is_manufacturing_part_lookup_prompt(prompt):
        return None
    part_no = parse_part_number_from_prompt(prompt)
    if not part_no:
        return None

    from solomon.opensearch.inspection_indices import search_documents_by_part_number
    from solomon.transport.config import get_opensearch_config

    plan = RetrievalPlan(
        strategy="KEYWORD",
        query=prompt.strip(),
        confidence=0.92,
        reasoning="manufacturing part number lookup (inspection-*)",
        entity_hint=part_no,
    )
    if get_opensearch_config() is None:
        md = (
            "OpenSearch が未設定です。品番検索には CDE の `inspection-*` が必要です。"
            " `OPENSEARCH_URL` / 認証 env を設定してください。"
        )
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(plan=plan, hits=[], errors=[{"source": "opensearch", "message": md}]),
            answer_markdown=md,
        )

    docs = search_documents_by_part_number(part_no, size=50)
    if not docs:
        md = (
            f"品番 **{part_no}** に一致する Bronze ドキュメントが `inspection-*` に見つかりません。"
            " Search タブで `3061042090` を検索するか、CDE 取込を確認してください。"
        )
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(
                plan=plan,
                hits=[],
                errors=[{"source": "opensearch", "message": "no hits on inspection-*"}],
            ),
            answer_markdown=md,
        )

    hits = [
        SourceHit(
            source="opensearch",
            kind="inspection_part_lookup",
            payload=doc,
            score=doc.get("score"),
        )
        for doc in docs[:20]
    ]
    md = format_part_lookup_markdown(part_no, docs)
    return KnowledgeRagResult(
        plan=plan,
        bundle=RetrievalBundle(plan=plan, hits=hits, errors=[]),
        answer_markdown=md,
    )


def try_answer_manufacturing_trace_prompt(
    prompt: str,
    *,
    user_ctx: UserContext | None = None,
) -> Optional[KnowledgeRagResult]:
    """製造トレース詳細質問なら RAG をバイパスして表形式で返す。"""
    if not is_manufacturing_trace_detail_prompt(prompt):
        return None
    trace_id = parse_trace_id_from_prompt(prompt)
    if not trace_id:
        return None

    summary = fetch_trace_summary(trace_id, user_ctx=user_ctx)
    plan = RetrievalPlan(
        strategy="SQL_ANALYTICS" if summary.get("source") == "lakehouse" else "GRAPH_QUERY",
        query=prompt.strip(),
        confidence=0.95,
        reasoning="manufacturing trace QA (J5 shukken/kanken)",
        entity_hint=trace_id,
    )

    if summary.get("error") == "NEO4J_NOT_CONFIGURED":
        md = (
            "Neo4j が未設定です。`NEO4J_MODE=internal` で neo4j-launcher を起動するか、"
            "`NEO4J_URI` を設定してください。"
        )
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(plan=plan, hits=[], errors=[{"source": "neo4j", "message": md}]),
            answer_markdown=md,
        )

    if summary.get("error") == "NOT_FOUND":
        md = (
            f"機番 **{trace_id}** の出検・完検データが見つかりません。"
            "Trino: `iceberg.inspection_silver.silver_j5_shukken_id` / "
            "`silver_kanken_fields`、Neo4j: `AssemblyUnit` / `TestRecord` に"
            f" `trace_id={trace_id}` があるか確認してください。"
        )
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(plan=plan, hits=[], errors=[{"source": "lakehouse", "message": md}]),
            answer_markdown=md,
        )

    if summary.get("error"):
        md = f"参照に失敗しました: {summary['error']}"
        return KnowledgeRagResult(
            plan=plan,
            bundle=RetrievalBundle(
                plan=plan,
                hits=[],
                errors=[{"source": "lakehouse", "message": summary["error"]}],
            ),
            answer_markdown=md,
        )

    hit = SourceHit(
        source="lakehouse" if summary.get("source") == "lakehouse" else "neo4j",
        kind="manufacturing_trace_summary",
        payload=summary,
    )
    md = format_trace_summary_markdown(summary)
    return KnowledgeRagResult(
        plan=plan,
        bundle=RetrievalBundle(plan=plan, hits=[hit], errors=[]),
        answer_markdown=md,
    )


__all__ = [
    "parse_trace_id_from_prompt",
    "parse_part_number_from_prompt",
    "is_manufacturing_trace_detail_prompt",
    "is_manufacturing_part_lookup_prompt",
    "is_manufacturing_trace_documents_prompt",
    "fetch_trace_summary",
    "format_trace_summary_markdown",
    "format_part_lookup_markdown",
    "format_trace_documents_markdown",
    "parse_vb_path_terms",
    "is_vb_path_lookup_prompt",
    "format_vb_path_lookup_markdown",
    "is_manufacturing_trace_graph_prompt",
    "fetch_trace_graph_context",
    "format_trace_graph_markdown",
    "try_answer_manufacturing_trace_graph_prompt",
    "try_answer_vb_path_prompt",
    "try_answer_manufacturing_part_prompt",
    "try_answer_manufacturing_trace_documents_prompt",
    "try_answer_manufacturing_trace_prompt",
]
