"""Trino catalog 正規化。"""
from __future__ import annotations

from solomon.ingestion.models import ConflictAndPermissionsResult, ProposeSchemaAndNameResult
from solomon.transport.trino_catalog import resolve_trino_catalog


def test_resolve_trino_catalog_maps_ossie_to_iceberg() -> None:
    assert resolve_trino_catalog("ossie") == "iceberg"
    assert resolve_trino_catalog("OSSIE") == "iceberg"
    assert resolve_trino_catalog("iceberg") == "iceberg"
    assert resolve_trino_catalog(None) == "iceberg"


def test_propose_schema_normalizes_catalog() -> None:
    result = ProposeSchemaAndNameResult.model_validate(
        {
            "catalog": "ossie",
            "target_schema": "demo",
            "proposed_table_name": "t_sample",
            "columns": [
                {"name": "id", "trino_type": "BIGINT", "nullable": True, "role": "dimension"},
            ],
        }
    )
    assert result.catalog == "iceberg"


def test_guardrail_rechecks_fq_with_iceberg(monkeypatch) -> None:
    from unittest import mock

    from solomon.ingestion.tasks import conflict_permissions_guardrail
    from solomon.tools.iceberg import TableExistsTool

    conn = mock.MagicMock()
    cur = conn.cursor.return_value
    cur.fetchone.return_value = None
    monkeypatch.setattr(
        "solomon.ingestion.permissions.TableExistsTool",
        lambda: mock.Mock(
            _run=lambda **_kw: {
                "status": "ok",
                "exists": False,
                "catalog": "iceberg",
                "schema": "demo",
                "table": "t_sample",
            }
        ),
    )
    monkeypatch.setattr(
        "solomon.tools.iceberg.trino_connection_for_user",
        lambda *_a, **_kw: conn,
    )

    out = ConflictAndPermissionsResult(
        has_conflict=False,
        has_create_priv=False,
        resolved_table="ossie.demo.t_sample",
        message="Catalog ossie not found",
    )
    ok_, msg = conflict_permissions_guardrail(out)
    assert ok_ is True
    assert msg is None


def test_conflict_result_normalizes_resolved_table() -> None:
    result = ConflictAndPermissionsResult.model_validate(
        {
            "has_conflict": False,
            "has_create_priv": True,
            "resolved_table": "ossie.demo.t_sample",
        }
    )
    assert result.resolved_table == "iceberg.demo.t_sample"
