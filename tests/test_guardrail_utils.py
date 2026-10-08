"""guardrail / schema 正規化の単体テスト。"""
from __future__ import annotations

from solomon.ingestion.models import ConflictAndPermissionsResult
from solomon.ingestion.tasks import conflict_permissions_guardrail
from solomon.tools.iceberg import TableExistsArgs
from solomon.tools.trino import TrinoMetaArgs
from solomon.transport.guardrail import parse_guardrail_model, unwrap_task_output


class _TaskOutput:
    def __init__(self, json_dict: dict) -> None:
        self.pydantic = None
        self.json_dict = json_dict
        self.raw = None


def test_unwrap_task_output_json_dict() -> None:
    payload = {"has_conflict": False}
    assert unwrap_task_output(_TaskOutput(payload)) == payload


def test_parse_guardrail_model_from_task_output() -> None:
    model, err = parse_guardrail_model(
        _TaskOutput(
            {
                "has_conflict": False,
                "has_create_priv": True,
                "resolved_table": "demo_table",
            }
        ),
        ConflictAndPermissionsResult,
    )
    assert err is None
    assert model is not None
    assert model.resolved_table == "demo_table"


def test_table_exists_args_accepts_target_schema_alias() -> None:
    args = TableExistsArgs.model_validate(
        {"catalog": "iceberg", "target_schema": "demo", "table": "orders"}
    )
    assert args.schema_ == "demo"


def test_trino_meta_args_accepts_target_schema_alias() -> None:
    args = TrinoMetaArgs.model_validate(
        {"catalog": "iceberg", "target_schema": "demo", "table": "orders"}
    )
    assert args.schema_ == "demo"


def test_table_exists_run_accepts_target_schema_kwarg(monkeypatch) -> None:
    from unittest import mock

    from solomon.tools.iceberg import TableExistsTool

    conn = mock.MagicMock()
    cur = conn.cursor.return_value
    cur.fetchone.return_value = None
    monkeypatch.setattr(
        "solomon.tools.iceberg.trino_connection_for_user",
        lambda *_a, **_kw: conn,
    )

    result = TableExistsTool()._run(
        catalog="iceberg",
        target_schema="demo",
        table="orders",
    )
    assert result["status"] == "ok"
    assert result["schema"] == "demo"
