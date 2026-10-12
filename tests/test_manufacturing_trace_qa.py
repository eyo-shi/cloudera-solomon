"""J5 製造トレース QA (デモプロンプト) のユニットテスト。"""

from __future__ import annotations

from solomon.graph.manufacturing.trace_qa import (
    _merge_trace_summaries,
    format_trace_summary_markdown,
    is_manufacturing_part_lookup_prompt,
    is_manufacturing_trace_detail_prompt,
    is_manufacturing_trace_documents_prompt,
    is_manufacturing_trace_graph_prompt,
    is_vb_path_lookup_prompt,
    parse_part_number_from_prompt,
    parse_trace_id_from_prompt,
    parse_vb_machine_from_prompt,
    parse_vb_path_terms,
    is_vb_machine_lookup_prompt,
    try_answer_manufacturing_part_prompt,
    try_answer_vb_machine_prompt,
    try_answer_manufacturing_trace_documents_prompt,
    try_answer_manufacturing_trace_graph_prompt,
    try_answer_vb_path_prompt,
)
from solomon.router.crew import heuristic_classify
from solomon.rag.classifier import is_knowledge_query
from solomon.graph.manufacturing.silver_trino import silver_schema_name

_DEMO_PROMPT = (
    "26G3V05307 の出検試験について、顧客品番、合格日時、ID メモリダンプの行数、"
    "アドレスマップから展開した項目が何件あるか教えて。"
    "同じ機番の完検では、測定項目は何行ある？"
)
_Q1_PART_PROMPT = (
    "品番 3061042090 が載っている試験データはどの種類？ファイル名も教えて。"
)
_Q2_TRACE_DOCS = "KIBAN 26G3V05354 に関係するドキュメントを全部見つけて。"
_Q3_VB_PATH = (
    "VB 圧無 や 蘇州 みたいなフォルダ名が付いている VB 試験ファイルはある？"
)
_Q4_TRACE_GRAPH = (
    "26G3V05390 という製品トレースについて、取り込んだ ソースファイル と "
    "KIBAN の関係をグラフで説明して。"
)
_Q5_VB_MACHINE = (
    "Neo4j 上で V/B 机番 166890 に結びついている試験は？判定は？"
)


def test_parse_trace_id() -> None:
    assert parse_trace_id_from_prompt(_DEMO_PROMPT) == "26G3V05307"


def test_is_manufacturing_trace_detail_prompt() -> None:
    assert is_manufacturing_trace_detail_prompt(_DEMO_PROMPT) is True
    assert is_manufacturing_trace_detail_prompt("こんにちは") is False


def test_q1_part_number_prompt() -> None:
    assert parse_part_number_from_prompt(_Q1_PART_PROMPT) == "3061042090"
    assert is_manufacturing_part_lookup_prompt(_Q1_PART_PROMPT) is True
    assert is_manufacturing_part_lookup_prompt(_DEMO_PROMPT) is False


def test_q2_trace_documents_prompt() -> None:
    assert parse_trace_id_from_prompt(_Q2_TRACE_DOCS) == "26G3V05354"
    assert is_manufacturing_trace_documents_prompt(_Q2_TRACE_DOCS) is True
    assert is_manufacturing_trace_detail_prompt(_Q2_TRACE_DOCS) is False
    assert is_knowledge_query(_Q2_TRACE_DOCS) is True
    assert heuristic_classify(_Q2_TRACE_DOCS).intent == "KNOWLEDGE_RAG"


def test_try_answer_trace_documents_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.transport.config.get_opensearch_config",
        lambda: object(),
    )
    monkeypatch.setattr(
        "solomon.opensearch.inspection_indices.search_documents_by_trace_id",
        lambda _tid, **kw: [
            {
                "format": "j5_main_id",
                "title": "20260707235801_26G3V05354.txt",
                "trace_id": "26G3V05354",
                "object_key": "j5_main_id/20260707235801_26G3V05354.txt",
                "payload": {"hinban": "3061042090", "kiban": "26G3V05354"},
            },
        ],
    )
    result = try_answer_manufacturing_trace_documents_prompt(_Q2_TRACE_DOCS)
    assert result is not None
    assert "26G3V05354" in result.answer_markdown
    assert "j5_main_id" in result.answer_markdown


def test_q5_vb_machine_prompt() -> None:
    assert parse_vb_machine_from_prompt(_Q5_VB_MACHINE) == "166890"
    assert is_vb_machine_lookup_prompt(_Q5_VB_MACHINE) is True
    assert heuristic_classify(_Q5_VB_MACHINE).intent == "KNOWLEDGE_RAG"


def test_try_answer_vb_machine_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.graph.manufacturing.trace_qa.fetch_vb_machine_context",
        lambda _vb, **kw: {
            "vb_machine_no": "166890",
            "vb_tests": [
                {
                    "product_trace_id": "unknown",
                    "source_files": [{"key": "vb_test/x.TXT", "format": "vb"}],
                },
            ],
            "silver_vb": [
                {
                    "object_key": "vb_test/蘇州/x.TXT",
                    "vb_machine_no": "166890",
                    "judge": "NG",
                },
            ],
        },
    )
    result = try_answer_vb_machine_prompt(_Q5_VB_MACHINE)
    assert result is not None
    assert "VB_TEST" in result.answer_markdown
    assert "NG" in result.answer_markdown


def test_q4_trace_graph_prompt() -> None:
    assert parse_trace_id_from_prompt(_Q4_TRACE_GRAPH) == "26G3V05390"
    assert is_manufacturing_trace_graph_prompt(_Q4_TRACE_GRAPH) is True
    assert heuristic_classify(_Q4_TRACE_GRAPH).intent == "KNOWLEDGE_RAG"
    assert heuristic_classify(_Q4_TRACE_GRAPH).needs_clarification is False


def test_try_answer_trace_graph_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.graph.manufacturing.trace_qa.fetch_trace_graph_context",
        lambda _tid, **kw: {
            "trace_id": "26G3V05390",
            "model": "bronze",
            "source": "neo4j",
            "neo4j_source_files": [
                {
                    "key": "j5_main_id/a.txt",
                    "format": "j5_main_id",
                    "product_trace_id": "26G3V05390",
                },
            ],
        },
    )
    result = try_answer_manufacturing_trace_graph_prompt(_Q4_TRACE_GRAPH)
    assert result is not None
    assert "HAS_KIBAN" in result.answer_markdown
    assert "INGESTED_INTO" in result.answer_markdown
    assert "j5_main_id/a.txt" in result.answer_markdown


def test_q3_vb_path_prompt() -> None:
    terms = parse_vb_path_terms(_Q3_VB_PATH)
    assert "圧無" in terms
    assert "蘇州" in terms
    assert is_vb_path_lookup_prompt(_Q3_VB_PATH) is True
    assert is_knowledge_query(_Q3_VB_PATH) is True
    assert heuristic_classify(_Q3_VB_PATH).intent == "KNOWLEDGE_RAG"


def test_try_answer_vb_path_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.transport.config.get_opensearch_config",
        lambda: object(),
    )
    monkeypatch.setattr(
        "solomon.opensearch.inspection_indices.search_vb_documents_by_path_terms",
        lambda terms, **kw: [
            {
                "format": "vb",
                "title": "18113000005200001012113.TXT",
                "object_key": "vb_test/VB_圧無/sample/18113000005200001012113.TXT",
                "payload": {"vb_machine_no": "0000101211", "judge": "NG"},
            },
        ],
    )
    result = try_answer_vb_path_prompt(_Q3_VB_PATH)
    assert result is not None
    assert "VB_圧無" in result.answer_markdown or "圧無" in result.answer_markdown
    assert "18113000005200001012113.TXT" in result.answer_markdown


def test_try_answer_part_prompt_opensearch(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.transport.config.get_opensearch_config",
        lambda: object(),
    )
    monkeypatch.setattr(
        "solomon.opensearch.inspection_indices.search_documents_by_part_number",
        lambda _pn, **kw: [
            {
                "format": "j5_main_id",
                "title": "20260707235801_26G3V05354.txt",
                "trace_id": "26G3V05354",
                "object_key": "j5_main_id/20260707235801_26G3V05354.txt",
                "score": 1.0,
            },
        ],
    )
    result = try_answer_manufacturing_part_prompt(_Q1_PART_PROMPT)
    assert result is not None
    assert "3061042090" in result.answer_markdown
    assert "j5_main_id" in result.answer_markdown
    assert "20260707235801_26G3V05354.txt" in result.answer_markdown


def test_silver_schema_default() -> None:
    assert silver_schema_name() == "inspection_silver"


def test_merge_silver_over_neo4j() -> None:
    merged = _merge_trace_summaries(
        {
            "trace_id": "26G3V05307",
            "source": "lakehouse",
            "customer_part_no": "3061042090",
            "dump_row_count": 512,
            "shukken_decoded_field_count": 70,
        },
        {"trace_id": "26G3V05307", "kanken_measurement_rows": 34},
        "26G3V05307",
    )
    assert merged["customer_part_no"] == "3061042090"
    assert merged["kanken_measurement_rows"] == 34


def test_format_trace_summary_markdown_demo_table() -> None:
    md = format_trace_summary_markdown(
        {
            "trace_id": "26G3V05307",
            "customer_part_no": "3061042090",
            "pass_datetime": "2026/07/08 00:28:54",
            "dump_row_count": 512,
            "shukken_decoded_field_count": 70,
            "kanken_measurement_rows": 34,
        }
    )
    assert "3061042090" in md
    assert "2026/07/08 00:28:54" in md
    assert "512" in md
    assert "約 70 件" in md
    assert "34 行" in md
