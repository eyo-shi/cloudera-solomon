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
    is_manufacturing_ingest_ledger_prompt,
    is_manufacturing_kanken_measurements_prompt,
    is_manufacturing_id_field_judge_prompt,
    is_manufacturing_id_dump_alt_kiban_prompt,
    is_manufacturing_dual_timing_kiban_prompt,
    is_manufacturing_vb_ng_list_prompt,
    is_vb_machine_lookup_prompt,
    parse_list_limit_from_prompt,
    try_answer_manufacturing_kanken_measurements_prompt,
    try_answer_manufacturing_id_field_judge_prompt,
    try_answer_manufacturing_id_dump_alt_kiban_prompt,
    try_answer_manufacturing_dual_timing_kiban_prompt,
    try_answer_manufacturing_vb_ng_list_prompt,
    is_manufacturing_trace_bundle_report_prompt,
    try_answer_manufacturing_trace_bundle_report_prompt,
    try_answer_manufacturing_ingest_ledger_prompt,
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
_Q6_INGEST_LEDGER = (
    "26G3V05319 について、完検・出検・メインID のどれが取り込み済みか、"
    "フォーマット別に件数とファイルパスを出して。"
)
_Q7_KANKEN_MEASUREMENTS = (
    "26G3V05319 の完検で、モータトルク や EOP 電流 に関する"
    "測定項目と初検値を一覧して。"
)
_Q8_ID_FIELD_JUDGE = (
    "メインID の 26G3V05390 で、T447 マップ上 判定が『未検』 の項目名を教えて。"
)
_Q9_DUAL_TIMING = (
    "同じ trace_id で 出検と完検の両方がある KIBAN を 5 件挙げ、"
    "それぞれ何ファイルあるか。"
)
_Q10_VB_NG_LIST = (
    "VB 試験で総合判定 NG の机番を洗い出し、それぞれ ステップ数 と "
    "試験日時、S3 上のパス までまとめて。"
)
_Q11_ID_DUMP_ALT_KIBAN = (
    "26G3V05390 のメインIDダンプで、別 KIBAN らしき文字列が hex 内に"
    "埋まっていないか調べ、信頼度付きで説明して。"
)
_Q12_TRACE_BUNDLE = (
    "KIBAN 26G3V05319 を起点に、取込済み試験の種類、完検の代表測定 3 項目、"
    "出検の通過日時、Neo4j 上の Product–File 関係を、根拠テーブル名付きでレポートして。"
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


def test_q12_trace_bundle_report_prompt() -> None:
    assert parse_trace_id_from_prompt(_Q12_TRACE_BUNDLE) == "26G3V05319"
    assert is_manufacturing_trace_bundle_report_prompt(_Q12_TRACE_BUNDLE) is True
    assert is_manufacturing_ingest_ledger_prompt(_Q12_TRACE_BUNDLE) is False
    assert heuristic_classify(_Q12_TRACE_BUNDLE).intent == "KNOWLEDGE_RAG"


def test_try_answer_trace_bundle_report_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.graph.manufacturing.trace_qa.fetch_trace_bundle_report_context",
        lambda _tid, **kw: {
            "trace_id": "26G3V05319",
            "silver_schema": "inspection_silver",
            "sources_used": [
                "Iceberg `inspection_silver.ingest_file_state`",
                "OpenSearch `inspection-*`",
                "Iceberg `inspection_silver.silver_kanken_fields`",
                "Neo4j Bronze (`Product` / `SourceFile` / `Kiban`)",
            ],
            "ingest_ledger": {
                "by_format": {"j5_shukken_id": ["a.DAT"], "kanken": ["b.txt"]},
            },
            "opensearch_by_format": {"j5_shukken_id": 1, "kanken": 1},
            "kanken_sample": {
                "rows": [
                    {
                        "step_name": "S1",
                        "symbol_name": "TRQ001",
                        "unit": "Nm",
                        "first_value": "1.2",
                    },
                ],
            },
            "trace_summary": {"pass_datetime": "2026/07/08 00:32:48"},
            "trace_graph": {
                "neo4j_source_files": [
                    {"format": "j5_shukken_id", "key": "j5_shukken_id/a.DAT", "product_trace_id": "26G3V05319"},
                ],
            },
        },
    )
    result = try_answer_manufacturing_trace_bundle_report_prompt(_Q12_TRACE_BUNDLE)
    assert result is not None
    assert result.plan.strategy == "COMPOSITE"
    assert "代表測定" in result.answer_markdown
    assert "通過日時" in result.answer_markdown
    assert "Neo4j" in result.answer_markdown
    assert "覚えなくても" in result.answer_markdown


def test_q11_id_dump_alt_kiban_prompt() -> None:
    assert parse_trace_id_from_prompt(_Q11_ID_DUMP_ALT_KIBAN) == "26G3V05390"
    assert is_manufacturing_id_dump_alt_kiban_prompt(_Q11_ID_DUMP_ALT_KIBAN) is True
    assert is_manufacturing_trace_detail_prompt(_Q11_ID_DUMP_ALT_KIBAN) is False
    assert is_manufacturing_id_field_judge_prompt(_Q11_ID_DUMP_ALT_KIBAN) is False
    assert heuristic_classify(_Q11_ID_DUMP_ALT_KIBAN).intent == "KNOWLEDGE_RAG"


def test_try_answer_id_dump_alt_kiban_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.graph.manufacturing.silver_trino.fetch_id_dump_alt_kiban_links",
        lambda _tid, **kw: {
            "trace_id": "26G3V05390",
            "silver_schema": "inspection_silver",
            "link_type": "id_dump_alt_kiban",
            "rows": [
                {
                    "trace_id": "26G3V05390",
                    "vb_machine_no": "26G0004225726",
                    "link_type": "id_dump_alt_kiban",
                    "confidence": "low",
                    "detail": "hex scan: embedded KIBAN-like token",
                    "source_object_key": "j5_main_id/20260707235801_26G3V05390.txt",
                },
            ],
        },
    )
    result = try_answer_manufacturing_id_dump_alt_kiban_prompt(_Q11_ID_DUMP_ALT_KIBAN)
    assert result is not None
    assert "silver_trace_links" in result.answer_markdown
    assert "26G0004225726" in result.answer_markdown
    assert "low" in result.answer_markdown.lower()


def test_q10_vb_ng_list_prompt() -> None:
    assert is_manufacturing_vb_ng_list_prompt(_Q10_VB_NG_LIST) is True
    assert is_vb_machine_lookup_prompt(_Q10_VB_NG_LIST) is False
    assert heuristic_classify(_Q10_VB_NG_LIST).intent == "KNOWLEDGE_RAG"
    assert heuristic_classify(_Q10_VB_NG_LIST).needs_clarification is False


def test_try_answer_vb_ng_list_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.graph.manufacturing.trace_qa.fetch_vb_ng_list_context",
        lambda **kw: {
            "source": "lakehouse+opensearch",
            "silver_schema": "inspection_silver",
            "judge_filter": "NG",
            "rows": [
                {
                    "vb_machine_no": "166890",
                    "step_count": 12,
                    "test_datetime": "2026/07/08 10:00:00",
                    "object_key": "vb_test/蘇州/sample/18113000005200001012113.TXT",
                    "judge": "NG",
                },
            ],
        },
    )
    result = try_answer_manufacturing_vb_ng_list_prompt(_Q10_VB_NG_LIST)
    assert result is not None
    assert "silver_vb" in result.answer_markdown
    assert "166890" in result.answer_markdown
    assert "18113000005200001012113.TXT" in result.answer_markdown


def test_q9_dual_timing_kiban_prompt() -> None:
    assert parse_trace_id_from_prompt(_Q9_DUAL_TIMING) is None
    assert parse_list_limit_from_prompt(_Q9_DUAL_TIMING) == 5
    assert is_manufacturing_dual_timing_kiban_prompt(_Q9_DUAL_TIMING) is True
    assert is_manufacturing_ingest_ledger_prompt(_Q9_DUAL_TIMING) is False
    assert is_manufacturing_trace_detail_prompt(_Q9_DUAL_TIMING) is False
    assert heuristic_classify(_Q9_DUAL_TIMING).intent == "KNOWLEDGE_RAG"


def test_try_answer_dual_timing_kiban_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.graph.manufacturing.silver_trino.fetch_kiban_with_shukken_and_kanken",
        lambda limit, **kw: {
            "source": "lakehouse",
            "silver_schema": "inspection_silver",
            "limit": limit,
            "rows": [
                {
                    "trace_id": "26G3V05319",
                    "shukken_cnt": 1,
                    "kanken_cnt": 1,
                    "total_cnt": 2,
                },
                {
                    "trace_id": "26G3V05393",
                    "shukken_cnt": 1,
                    "kanken_cnt": 2,
                    "total_cnt": 3,
                },
            ],
        },
    )
    result = try_answer_manufacturing_dual_timing_kiban_prompt(_Q9_DUAL_TIMING)
    assert result is not None
    assert "ingest_file_state" in result.answer_markdown
    assert "26G3V05319" in result.answer_markdown
    assert "出検" in result.answer_markdown
    assert "完検" in result.answer_markdown
    assert "| 0 |" not in result.answer_markdown


def test_q8_id_field_judge_prompt() -> None:
    assert parse_trace_id_from_prompt(_Q8_ID_FIELD_JUDGE) == "26G3V05390"
    assert is_manufacturing_id_field_judge_prompt(_Q8_ID_FIELD_JUDGE) is True
    assert is_manufacturing_trace_detail_prompt(_Q8_ID_FIELD_JUDGE) is False
    assert heuristic_classify(_Q8_ID_FIELD_JUDGE).intent == "KNOWLEDGE_RAG"


def test_try_answer_id_field_judge_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.graph.manufacturing.silver_trino.fetch_id_fields_by_judge",
        lambda _tid, **kw: {
            "trace_id": "26G3V05390",
            "silver_schema": "inspection_silver",
            "data_format": "j5_main_id",
            "value_judge": "未検",
            "rows": [
                {
                    "field_name": "製造区分コード",
                    "address_hex": "0120(H)",
                    "value_judge": "未検",
                    "value": "00",
                    "process_name": "生産指示",
                },
            ],
        },
    )
    result = try_answer_manufacturing_id_field_judge_prompt(_Q8_ID_FIELD_JUDGE)
    assert result is not None
    assert "silver_id_fields" in result.answer_markdown
    assert "製造区分コード" in result.answer_markdown
    assert "未検" in result.answer_markdown


def test_q7_kanken_measurements_prompt() -> None:
    assert parse_trace_id_from_prompt(_Q7_KANKEN_MEASUREMENTS) == "26G3V05319"
    assert is_manufacturing_kanken_measurements_prompt(_Q7_KANKEN_MEASUREMENTS) is True
    assert is_manufacturing_trace_detail_prompt(_Q7_KANKEN_MEASUREMENTS) is False
    assert heuristic_classify(_Q7_KANKEN_MEASUREMENTS).intent == "KNOWLEDGE_RAG"


def test_try_answer_kanken_measurements_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.graph.manufacturing.silver_trino.fetch_kanken_measurements_for_trace",
        lambda _tid, terms, user_ctx=None, **kw: {
            "trace_id": "26G3V05319",
            "silver_schema": "inspection_silver",
            "filter_terms": terms,
            "rows": [
                {
                    "step_name": "2回転下降_作動確認",
                    "symbol_name": "TRQ02モータトルク(STEP02)",
                    "unit": "Nm",
                    "spec_lower": "3.0",
                    "spec_upper": "7.0",
                    "first_value": "4.41",
                    "j_reinspect": "0",
                },
                {
                    "step_name": "2回転下降_作動確認",
                    "symbol_name": "EOP02EOP電流(STEP02)",
                    "unit": "A",
                    "first_value": "3.51",
                    "j_reinspect": "0",
                },
            ],
        },
    )
    result = try_answer_manufacturing_kanken_measurements_prompt(_Q7_KANKEN_MEASUREMENTS)
    assert result is not None
    assert "silver_kanken_fields" in result.answer_markdown
    assert "TRQ02" in result.answer_markdown
    assert "4.41" in result.answer_markdown
    assert "EOP02" in result.answer_markdown


def test_q6_ingest_ledger_prompt() -> None:
    assert parse_trace_id_from_prompt(_Q6_INGEST_LEDGER) == "26G3V05319"
    assert is_manufacturing_ingest_ledger_prompt(_Q6_INGEST_LEDGER) is True
    assert is_manufacturing_trace_detail_prompt(_Q6_INGEST_LEDGER) is False
    assert heuristic_classify(_Q6_INGEST_LEDGER).intent == "KNOWLEDGE_RAG"
    assert heuristic_classify(_Q6_INGEST_LEDGER).needs_clarification is False


def test_try_answer_ingest_ledger_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "solomon.graph.manufacturing.trace_qa.fetch_ingest_ledger_context",
        lambda _tid, **kw: {
            "trace_id": "26G3V05319",
            "silver_schema": "inspection_silver",
            "by_format": {
                "j5_main_id": ["j5_main_id/a.txt"],
                "kanken": ["j5_kanken/b.txt", "j5_kanken/c.txt"],
            },
        },
    )
    result = try_answer_manufacturing_ingest_ledger_prompt(_Q6_INGEST_LEDGER)
    assert result is not None
    assert "j5_main_id" in result.answer_markdown
    assert "完検" in result.answer_markdown
    assert "j5_kanken/b.txt" in result.answer_markdown


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
    assert "solomon://graph-cypher?" in result.answer_markdown
    assert "vb_id" in result.answer_markdown


def test_q4_trace_graph_prompt() -> None:
    assert parse_trace_id_from_prompt(_Q4_TRACE_GRAPH) == "26G3V05390"
    assert is_manufacturing_trace_graph_prompt(_Q4_TRACE_GRAPH) is True
    assert is_manufacturing_trace_documents_prompt(_Q4_TRACE_GRAPH) is False
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
