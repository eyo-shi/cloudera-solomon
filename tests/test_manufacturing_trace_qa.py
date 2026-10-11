"""J5 製造トレース QA (デモプロンプト) のユニットテスト。"""

from __future__ import annotations

from solomon.graph.manufacturing.trace_qa import (
    _merge_trace_summaries,
    format_trace_summary_markdown,
    is_manufacturing_trace_detail_prompt,
    parse_trace_id_from_prompt,
)
from solomon.graph.manufacturing.silver_trino import silver_schema_name

_DEMO_PROMPT = (
    "26G3V05307 の出検試験について、顧客品番、合格日時、ID メモリダンプの行数、"
    "アドレスマップから展開した項目が何件あるか教えて。"
    "同じ機番の完検では、測定項目は何行ある？"
)


def test_parse_trace_id() -> None:
    assert parse_trace_id_from_prompt(_DEMO_PROMPT) == "26G3V05307"


def test_is_manufacturing_trace_detail_prompt() -> None:
    assert is_manufacturing_trace_detail_prompt(_DEMO_PROMPT) is True
    assert is_manufacturing_trace_detail_prompt("こんにちは") is False


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
