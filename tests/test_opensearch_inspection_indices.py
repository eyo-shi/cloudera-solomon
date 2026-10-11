"""CDE inspection-* インデックス名ヘルパ。"""

from __future__ import annotations

from solomon.opensearch.inspection_indices import (
    inspection_index_list_csv,
    inspection_index_name,
    inspection_index_prefix,
    summarize_trace_documents,
)


def test_inspection_index_prefix_default() -> None:
    assert inspection_index_prefix() == "inspection"


def test_inspection_index_names() -> None:
    assert inspection_index_name("kanken") == "inspection-kanken"
    assert inspection_index_name("j5_shukken_id") == "inspection-j5_shukken_id"
    assert "inspection-vb" in inspection_index_list_csv()


def test_summarize_trace_documents() -> None:
    text = summarize_trace_documents(
        [
            {"format": "j5_shukken_id", "object_key": "a.DAT"},
            {"format": "kanken", "object_key": "b.txt"},
        ]
    )
    assert text is not None
    assert "2 件" in text
    assert "j5_shukken_id=1" in text
