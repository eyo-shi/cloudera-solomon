"""Graph browse service unit tests."""

from __future__ import annotations

import pytest

from solomon.graph import browse
from solomon.graph.models import GraphNodeDTO


def test_validate_identifier_rejects_injection() -> None:
    with pytest.raises(ValueError, match="Invalid label"):
        browse.query_by_label("Customer; DROP")


def test_validate_relationship_type() -> None:
    with pytest.raises(ValueError, match="Invalid relationship type"):
        browse.query_by_relationship_type("USES`]->(x)")


def test_validate_property_key() -> None:
    with pytest.raises(ValueError, match="Invalid property key"):
        browse.query_by_property_key("name OR 1=1")


def test_json_safe_datetime() -> None:
    from datetime import datetime, timezone

    val = browse._json_safe(datetime(2024, 1, 2, tzinfo=timezone.utc))
    assert val == "2024-01-02T00:00:00+00:00"


def test_caption_prefers_name() -> None:
    assert browse._caption(["Dataset"], {"fq_name": "a.b.c", "name": "orders"}) == "orders"


class _FakeNode:
    def __init__(self, labels: list[str], props: dict) -> None:
        self.labels = labels
        self._props = props
        self.id = 42
        self.element_id = "4:abc:123"

    def __iter__(self):
        return iter(self._props.items())

    def keys(self):
        return self._props.keys()

    def values(self):
        return self._props.values()

    def items(self):
        return self._props.items()


def test_serialize_node_uses_business_id() -> None:
    node = _FakeNode(["System"], {"id": "sys:crm", "name": "CRM"})
    dto = browse._serialize_node(node)
    assert dto.id == "sys:crm"
    assert dto.caption == "CRM"


def test_collect_graph_deduplicates_nodes() -> None:
    n1 = _FakeNode(["Dataset"], {"id": "d1", "name": "orders"})
    n2 = _FakeNode(["Dataset"], {"id": "d1", "name": "orders"})
    records = [{"a": n1}, {"b": n2}]

    class _Rec:
        def __init__(self, data: dict) -> None:
            self._data = data

        def values(self):
            return self._data.values()

    viz = browse._collect_graph([_Rec(r) for r in records], limit=100)
    assert len(viz.nodes) == 1
    assert isinstance(viz.nodes[0], GraphNodeDTO)
