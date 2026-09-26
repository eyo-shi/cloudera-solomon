"""RetrievalBundle から最終回答 Markdown を生成する。"""

from __future__ import annotations

import json

from solomon.rag.models import KnowledgeRagResult, RetrievalBundle
from solomon.transport.llm import try_json_completion


def _format_bundle_for_llm(bundle: RetrievalBundle) -> str:
    sections: list[str] = []
    sections.append(f"Strategy: {bundle.plan.strategy}")
    sections.append(f"Query: {bundle.plan.query}")

    for hit in bundle.hits[:20]:
        sections.append(
            f"[{hit.source}/{hit.kind}] score={hit.score}\n"
            + json.dumps(hit.payload, ensure_ascii=False, default=str)[:2000]
        )

    for err in bundle.errors:
        sections.append(f"[error/{err['source']}] {err['message']}")

    return "\n\n".join(sections)


def _heuristic_markdown(bundle: RetrievalBundle) -> str:
    """LLM 未使用時の決定論的回答。"""
    lines = [f"## 検索結果 ({bundle.plan.strategy})", ""]
    if not bundle.hits:
        lines.append("関連情報が見つかりませんでした。")
        for e in bundle.errors:
            lines.append(f"- ⚠ {e['source']}: {e['message']}")
        return "\n".join(lines)

    for hit in bundle.hits[:10]:
        lines.append(f"### {hit.source} / {hit.kind}")
        if hit.source == "neo4j":
            for rec in hit.payload.get("records", [])[:5]:
                lines.append(f"- `{rec}`")
        elif hit.source == "lakehouse":
            lines.append(f"- SQL: `{hit.payload.get('sql', '')}`")
            rows = hit.payload.get("rows") or []
            lines.append(f"- 行数: {hit.payload.get('row_count', len(rows))}")
            for row in rows[:5]:
                lines.append(f"  - {row}")
        elif hit.source in ("opensearch", "ossie"):
            fq = hit.payload.get("fq_name", "")
            score = hit.score or hit.payload.get("score")
            desc = (hit.payload.get("dataset") or {}).get("description", "")
            lines.append(f"- **{fq}** (score={score}): {desc[:120]}")
        lines.append("")

    if bundle.errors:
        lines.append("### 注意")
        for e in bundle.errors:
            lines.append(f"- {e['source']}: {e['message']}")

    return "\n".join(lines)


def synthesize_answer(bundle: RetrievalBundle) -> KnowledgeRagResult:
    """RetrievalBundle を Markdown 回答に変換する。"""
    context = _format_bundle_for_llm(bundle)
    llm_out = try_json_completion(
        (
            "You are a data catalog assistant. Using ONLY the retrieval results below, "
            "write a concise Japanese Markdown answer. Cite sources (neo4j/opensearch/lakehouse).\n\n"
            f"{context}\n\n"
            'Return JSON: {"answer_markdown": "## ..."}'
        ),
        max_tokens=1024,
        temperature=0.2,
    )

    sql_executed = None
    for hit in bundle.hits:
        if hit.source == "lakehouse" and hit.kind == "sql":
            sql_executed = hit.payload.get("sql")
            break

    if llm_out and isinstance(llm_out.get("answer_markdown"), str):
        answer = llm_out["answer_markdown"]
    else:
        answer = _heuristic_markdown(bundle)

    return KnowledgeRagResult(
        plan=bundle.plan,
        bundle=bundle,
        answer_markdown=answer,
        sql_executed=sql_executed,
    )


__all__ = ["synthesize_answer"]
