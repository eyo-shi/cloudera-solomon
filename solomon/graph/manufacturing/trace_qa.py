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
    "KIBAN",
)


def parse_trace_id_from_prompt(prompt: str) -> str | None:
    m = _TRACE_ID_RE.search(prompt.strip())
    return m.group(1).upper() if m else None


def is_manufacturing_trace_detail_prompt(prompt: str) -> bool:
    text = prompt.strip()
    if parse_trace_id_from_prompt(text) is None:
        return False
    lower = text.lower()
    return any(m in text or m.lower() in lower for m in _TRACE_PROMPT_MARKERS)


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
    "is_manufacturing_trace_detail_prompt",
    "fetch_trace_summary",
    "format_trace_summary_markdown",
    "try_answer_manufacturing_trace_prompt",
]
