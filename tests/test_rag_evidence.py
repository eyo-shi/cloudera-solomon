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


def _sql_hit(sql: str, row_count: int | None = None) -> SourceHit:
    return SourceHit(
        source="lakehouse",
        kind="sql",
        payload={"sql": sql, "columns": [], "rows": [], "row_count": row_count},
    )


def test_evidence_section_lists_every_sql_in_order() -> None:
    md = enrich_answer_with_evidence(
        "## 結論\nok",
        hits=[
            _sql_hit("SELECT COUNT(*) AS row_count FROM t LIMIT 10", 1),
            _sql_hit("SELECT *\n  FROM t\n  LIMIT 5", 5),
            _sql_hit("SELECT lot, COUNT(*) FROM t\nWHERE k = 'x'\nGROUP BY lot", 3),
        ],
        tool_calls=[],
        sql_executed="SELECT ignored",
    )
    assert "- SQL #1（1 行）: `SELECT COUNT(*) AS row_count FROM t LIMIT 10`" in md
    assert "- SQL #2（5 行）: `SELECT * FROM t LIMIT 5`" in md
    assert "- SQL #3（3 行）: `SELECT lot, COUNT(*) FROM t WHERE k = 'x' GROUP BY lot`" in md
    assert "SELECT ignored" not in md
    assert md.index("SQL #1") < md.index("SQL #2") < md.index("SQL #3")


def test_evidence_section_dedupes_and_caps_sql() -> None:
    hits = [_sql_hit(f"SELECT {i} FROM t") for i in range(7)]
    hits.append(_sql_hit("select 6   from t"))  # 空白・大小違いの重複
    md = enrich_answer_with_evidence("ok", hits=hits, tool_calls=[])
    assert "先行する 2 件は省略" in md
    assert "SQL #1:" not in md
    assert "- SQL #3: `SELECT 2 FROM t`" in md
    assert "- SQL #7: `SELECT 6 FROM t`" in md
    assert "SQL #8" not in md


def test_evidence_section_truncates_long_sql() -> None:
    long_sql = "SELECT " + ", ".join(f"col_{i}" for i in range(200)) + " FROM t"
    md = enrich_answer_with_evidence("ok", hits=[_sql_hit(long_sql)], tool_calls=[])
    line = next(ln for ln in md.splitlines() if ln.startswith("- SQL"))
    assert line.endswith("…`")
    assert len(line) < 330
