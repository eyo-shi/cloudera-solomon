"""Evidence 後処理（マーカー置換・根拠節）。"""

from __future__ import annotations

from solomon.rag.evidence import enrich_answer_with_evidence
from solomon.rag.models import SourceHit


def _doc_hit(doc_id: str, **extra: str) -> SourceHit:
    return SourceHit(
        source="opensearch",
        kind="document",
        payload={
            "documents": [
                {
                    "doc_id": doc_id,
                    "title": f"Title {doc_id}",
                    "chunk_id": extra.get("chunk_id", "c1"),
                    "doc_type_label": extra.get("doc_type_label", "Inquiry"),
                    "doc_date": extra.get("doc_date", "2024-01-02"),
                }
            ],
        },
    )


def test_replaces_valid_doc_and_graph_markers() -> None:
    tool_calls = [
        {
            "name": "graph_query",
            "ok": True,
            "args": {"cypher": "MATCH (n) RETURN n LIMIT 5", "params": {"id": "1"}},
        },
    ]
    hits = [_doc_hit("d-42")]
    md = enrich_answer_with_evidence(
        "根拠: 〔doc:d-42〕 と 〔graph:1〕 を確認。",
        hits=hits,
        tool_calls=tool_calls,
        sql_executed="SELECT 1",
    )
    assert "solomon://search-document?" in md
    assert "doc_id=d-42" in md or "doc_id=d-42" in md.replace("%2D", "-")
    assert "solomon://graph-cypher?" in md
    assert "MATCH" in md
    assert "### 根拠" in md
    assert "SELECT 1" in md


def test_unknown_doc_marker_left_plain() -> None:
    md = enrich_answer_with_evidence(
        "missing 〔doc:no-such〕 here",
        hits=[],
        tool_calls=[],
    )
    assert "〔doc:no-such〕" in md
    assert "solomon://search-document?" not in md


def test_unknown_graph_marker_left_plain() -> None:
    md = enrich_answer_with_evidence(
        "bad 〔graph:9〕",
        hits=[],
        tool_calls=[],
    )
    assert "〔graph:9〕" in md


def test_evidence_section_lists_sql_first_line() -> None:
    sql = "SELECT a,\n  b FROM t LIMIT 10"
    md = enrich_answer_with_evidence(
        "## 結論\nok",
        hits=[],
        tool_calls=[],
        sql_executed=sql,
    )
    assert "`SELECT a,`" in md or "`SELECT a," in md
