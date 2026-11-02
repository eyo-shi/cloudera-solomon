"""エージェント回答への Cypher / 文書リンクと「根拠」節の後処理。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from solomon.graph.chat_links import graph_cypher_markdown_link
from solomon.opensearch.chat_links import search_document_markdown_link
from solomon.rag.models import SourceHit
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

_DOC_MARKER = re.compile(r"〔doc:([^〕]+)〕")
_GRAPH_MARKER = re.compile(r"〔graph:(\d+)〕")


@dataclass
class _DocRecord:
    doc_id: str
    title: str
    chunk_id: str | None = None
    doc_type: str | None = None
    doc_type_label: str | None = None
    doc_date: str | None = None
    index: str | None = None


@dataclass
class EvidenceIndex:
    docs: dict[str, _DocRecord] = field(default_factory=dict)
    graphs: dict[int, dict[str, Any]] = field(default_factory=dict)
    sql: str | None = None


def _index_from_hits_and_tools(
    hits: list[SourceHit],
    tool_calls: list[dict[str, Any]],
) -> EvidenceIndex:
    idx = EvidenceIndex()
    graph_n = 0
    for tc in tool_calls:
        name = str(tc.get("name") or "")
        if name == "graph_query" and tc.get("ok"):
            graph_n += 1
            args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
            cypher = str(args.get("cypher") or "").strip()
            if cypher:
                params = args.get("params")
                if not isinstance(params, dict):
                    params = {}
                idx.graphs[graph_n] = {"cypher": cypher, "params": params}

    for hit in hits:
        if hit.source == "lakehouse" and not idx.sql:
            sql = hit.payload.get("sql")
            if isinstance(sql, str) and sql.strip():
                idx.sql = sql.strip()
        if hit.source != "opensearch" or hit.kind != "document":
            continue
        for doc in hit.payload.get("documents") or []:
            if not isinstance(doc, dict):
                continue
            doc_id = str(doc.get("doc_id") or "").strip()
            if not doc_id:
                continue
            title = str(doc.get("title") or doc_id)
            rec = _DocRecord(
                doc_id=doc_id,
                title=title,
                chunk_id=str(doc["chunk_id"]) if doc.get("chunk_id") else None,
                doc_type=str(doc["doc_type"]) if doc.get("doc_type") else None,
                doc_type_label=str(doc["doc_type_label"])
                if doc.get("doc_type_label")
                else None,
                doc_date=str(doc["doc_date"]) if doc.get("doc_date") else None,
                index=str(doc.get("index")) if doc.get("index") else None,
            )
            prev = idx.docs.get(doc_id)
            if prev is None or (rec.chunk_id and not prev.chunk_id):
                idx.docs[doc_id] = rec

    return idx


def _replace_markers(text: str, index: EvidenceIndex) -> tuple[str, set[str], set[int]]:
    cited_docs: set[str] = set()
    cited_graphs: set[int] = set()

    def doc_repl(match: re.Match[str]) -> str:
        doc_id = match.group(1).strip()
        rec = index.docs.get(doc_id)
        if not rec:
            _logger.warning("evidence.unknown_doc_marker", doc_id=doc_id)
            return match.group(0)
        cited_docs.add(doc_id)
        payload: dict[str, Any] = {
            "doc_id": rec.doc_id,
            "title": rec.title,
        }
        if rec.chunk_id:
            payload["chunk_id"] = rec.chunk_id
        if rec.index:
            payload["index"] = rec.index
        label = rec.title[:80] if rec.title else doc_id
        return search_document_markdown_link(label, payload)

    def graph_repl(match: re.Match[str]) -> str:
        try:
            n = int(match.group(1))
        except ValueError:
            _logger.warning("evidence.invalid_graph_marker", raw=match.group(1))
            return match.group(0)
        entry = index.graphs.get(n)
        if not entry:
            _logger.warning("evidence.unknown_graph_marker", n=n)
            return match.group(0)
        cited_graphs.add(n)
        return graph_cypher_markdown_link(
            str(entry["cypher"]),
            entry.get("params") if isinstance(entry.get("params"), dict) else {},
            label="グラフで見る",
        )

    out = _DOC_MARKER.sub(doc_repl, text)
    out = _GRAPH_MARKER.sub(graph_repl, out)
    return out, cited_docs, cited_graphs


def _append_evidence_section(
    text: str,
    index: EvidenceIndex,
    *,
    cited_docs: set[str],
    cited_graphs: set[int],
) -> str:
    lines: list[str] = ["", "### 根拠"]

    graph_keys = sorted(cited_graphs)[:3]
    if not graph_keys:
        graph_keys = sorted(index.graphs.keys())[-3:]
    for n in graph_keys:
        entry = index.graphs.get(n)
        if not entry:
            continue
        link = graph_cypher_markdown_link(
            str(entry["cypher"]),
            entry.get("params") if isinstance(entry.get("params"), dict) else {},
            label=f"グラフクエリ #{n}",
        )
        lines.append(f"- {link}")

    doc_ids = list(cited_docs) if cited_docs else []
    if not doc_ids and index.docs:
        doc_ids = list(index.docs.keys())[:5]
    for doc_id in doc_ids:
        rec = index.docs.get(doc_id)
        if not rec:
            continue
        parts = [rec.doc_type_label or rec.doc_type, rec.doc_date, rec.title]
        meta = " · ".join(p for p in parts if p)
        link = search_document_markdown_link(
            meta or rec.title,
            {
                "doc_id": rec.doc_id,
                **({"chunk_id": rec.chunk_id} if rec.chunk_id else {}),
                **({"index": rec.index} if rec.index else {}),
            },
        )
        lines.append(f"- {link}")

    if index.sql:
        first_line = index.sql.strip().splitlines()[0][:200]
        lines.append(f"- SQL: `{first_line}`")

    if len(lines) <= 1:
        return text
    return text.rstrip() + "\n" + "\n".join(lines) + "\n"


def enrich_answer_with_evidence(
    answer_markdown: str,
    *,
    hits: list[SourceHit],
    tool_calls: list[dict[str, Any]],
    sql_executed: str | None = None,
) -> str:
    """マーカー置換と根拠節の付与。"""
    text = (answer_markdown or "").strip()
    if not text:
        return text

    index = _index_from_hits_and_tools(hits, tool_calls)
    if sql_executed and not index.sql:
        index.sql = sql_executed.strip()

    replaced, cited_docs, cited_graphs = _replace_markers(text, index)
    return _append_evidence_section(
        replaced,
        index,
        cited_docs=cited_docs,
        cited_graphs=cited_graphs,
    )


__all__ = ["enrich_answer_with_evidence"]
