"""Run scenario ``search_checks`` (expansion off / on / keyword)."""

from __future__ import annotations

from typing import Any

from demo.validate.model import CheckResult


def _doc_ids(hits: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for h in hits:
        did = h.get("doc_id")
        if did:
            out.append(str(did))
    return out


def run_search_checks(
    checks: list[dict[str, Any]],
    *,
    use_opensearch: bool,
) -> tuple[list[CheckResult], list[dict[str, Any]], str]:
    """Returns results, table rows for CSV, markdown table body."""
    if not checks:
        return [], [], "_No search_checks in scenario._"

    if not use_opensearch:
        rows: list[dict[str, Any]] = []
        for chk in checks:
            cid = chk.get("id") or chk.get("name") or "check"
            for mode in ("expand_off", "expand_on", "keyword"):
                rows.append(
                    {
                        "check_id": cid,
                        "mode": mode,
                        "query": chk.get("query", ""),
                        "top_k": chk.get("top_k", 8),
                        "status": "skipped",
                        "top_doc_ids": "",
                    }
                )
        md = "| check | mode | status |\n| --- | --- | --- |\n"
        for r in rows:
            md += f"| {r['check_id']} | {r['mode']} | skipped (no OS) |\n"
        return (
            [
                CheckResult(
                    name="search_checks",
                    ok=True,
                    detail="skipped (OpenSearch not configured)",
                    category="cluster",
                )
            ],
            rows,
            md,
        )

    from solomon.opensearch.docs_search import search_documents, search_documents_with_expansion
    from solomon.transport.config import get_opensearch_config

    cfg = get_opensearch_config()
    if cfg is None:
        return (
            [CheckResult(name="search_checks", ok=False, detail="OPENSEARCH_* missing", category="cluster")],
            [],
            "",
        )

    results: list[CheckResult] = []
    rows: list[dict[str, Any]] = []
    md_lines = ["| check | mode | top doc_ids | pass |", "| --- | --- | --- | --- |"]

    for chk in checks:
        cid = str(chk.get("id") or chk.get("name") or "check")
        query = str(chk.get("query") or "")
        top_k = int(chk.get("top_k") or 8)
        filters = chk.get("filters")

        modes: list[tuple[str, str, bool | None]] = [
            ("expand_off", "hybrid", False),
            ("expand_on", "hybrid", True),
            ("keyword", "keyword", False),
        ]
        for mode_label, search_mode, expand in modes:
            q = query
            if mode_label == "keyword" and chk.get("keyword_query"):
                q = str(chk["keyword_query"])
            if expand is False and mode_label == "expand_off":
                resp = search_documents_with_expansion(
                    cfg, q, top_k=top_k, filters=filters, mode=search_mode, expand=False
                )
            elif expand is True:
                resp = search_documents_with_expansion(
                    cfg, q, top_k=top_k, filters=filters, mode=search_mode, expand=True
                )
            else:
                resp = search_documents(cfg, q, top_k=top_k, filters=filters, mode=search_mode)

            docs = resp.get("documents") or []
            ids = _doc_ids(docs)
            ok = _evaluate_search_expectations(chk, mode_label, ids)
            results.append(
                CheckResult(
                    name=f"search:{cid}:{mode_label}",
                    ok=ok,
                    detail=f"top={ids[:5]}",
                    category="cluster",
                )
            )
            rows.append(
                {
                    "check_id": cid,
                    "mode": mode_label,
                    "query": q,
                    "top_k": top_k,
                    "status": "pass" if ok else "fail",
                    "top_doc_ids": "|".join(ids[:top_k]),
                }
            )
            md_lines.append(
                f"| {cid} | {mode_label} | {', '.join(ids[:5])} | {'OK' if ok else 'FAIL'} |"
            )

    return results, rows, "\n".join(md_lines)


def _evaluate_search_expectations(chk: dict[str, Any], mode_label: str, doc_ids: list[str]) -> bool:
    ok = True
    for rule in chk.get("must_rank") or []:
        if not isinstance(rule, dict):
            continue
        modes = rule.get("modes") or [mode_label]
        if mode_label not in modes and mode_label not in [str(m) for m in modes]:
            continue
        doc_id = str(rule.get("doc_id") or "")
        max_rank = int(rule.get("max_rank") or 3)
        if doc_id and doc_id not in doc_ids[:max_rank]:
            ok = False
    for rule in chk.get("must_not_rank") or []:
        if not isinstance(rule, dict):
            continue
        modes = rule.get("modes") or [mode_label]
        if mode_label not in modes and mode_label not in [str(m) for m in modes]:
            continue
        doc_id = str(rule.get("doc_id") or "")
        max_rank = int(rule.get("max_rank") or 20)
        if doc_id and doc_id in doc_ids[:max_rank]:
            ok = False
    return ok


__all__ = ["run_search_checks"]
