"""Graph ingest router helpers."""

from __future__ import annotations

from solomon.router.graph_ingest import (
    build_graph_ingest_clarification,
    is_graph_ingest_request,
    parse_node_fields,
)


def test_is_graph_ingest_request() -> None:
    assert is_graph_ingest_request("ファイルをナレッジグラフに追加")
    assert not is_graph_ingest_request("テーブルをサマリーして")


def test_parse_node_fields_from_prompt() -> None:
    assert parse_node_fields("customer_id と product_name をノードに") == [
        "customer_id",
        "product_name",
    ]


def test_parse_node_fields_from_short_reply() -> None:
    assert parse_node_fields("customer_id, product_name") == [
        "customer_id",
        "product_name",
    ]


def test_build_graph_ingest_clarification_lists_columns() -> None:
    text = build_graph_ingest_clarification(
        key="data/customers.csv",
        column_names=["customer_id", "name"],
    )
    assert "customer_id" in text
    assert "ノード" in text
