"""Neo4j graph load Tool for ingestion metadata."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from solomon.graph.config import get_neo4j_config
from solomon.graph.neo4j_loader import ColumnGraphNode, IngestionGraphLoader, IngestionGraphPayload
from solomon.transport.errors import ErrorCode, err, ok
from solomon.transport.logging import get_logger
from solomon.transport.tool_base import BaseSolomonTool
from solomon.transport.user_context import UserContext

_logger = get_logger(__name__)


class ColumnGraphInput(BaseModel):
    name: str
    trino_type: str
    nullable: bool = True
    role: str = "dimension"
    description: Optional[str] = None


class Neo4jGraphLoadArgs(BaseModel):
    catalog: str = Field("iceberg")
    schema_: str = Field(..., alias="schema")
    table: str = Field(...)
    columns: list[ColumnGraphInput] = Field(..., min_length=1)
    bucket: str = Field(...)
    key: str = Field(...)
    format: str = Field(...)
    sheet: Optional[str] = None
    header_row: Optional[int] = None
    meta_kv: list[dict[str, Any]] = Field(default_factory=list)
    row_count_hint: Optional[int] = None

    model_config = {"populate_by_name": True}


class Neo4jGraphLoadTool(BaseSolomonTool):
    """Create Dataset / Column / SourceFile nodes and relationships in Neo4j.

    Iceberg テーブル作成後に呼び出し、取り込みメタデータをグラフDBへ反映する。
    NEO4J_URI が未設定の場合は ``NEO4J_NOT_CONFIGURED`` を返す。
    """

    name: str = "neo4j_graph_load"
    description: str = (
        "Load ingestion metadata into Neo4j as graph nodes and relationships. "
        "Creates Dataset, Column, SourceFile, Schema, and optional MetadataEntry "
        "nodes, then links them with HAS_COLUMN, IN_SCHEMA, SOURCED_FROM, and "
        "HAS_METADATA relationships. Call after Iceberg table creation."
    )
    args_schema: type[BaseModel] = Neo4jGraphLoadArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        catalog: str,
        schema: str,
        table: str,
        columns: list[dict[str, Any]] | list[ColumnGraphInput],
        bucket: str,
        key: str,
        format: str,
        sheet: Optional[str] = None,
        header_row: Optional[int] = None,
        meta_kv: Optional[list[dict[str, Any]]] = None,
        row_count_hint: Optional[int] = None,
        **_: Any,
    ) -> dict[str, Any]:
        config = get_neo4j_config()
        if config is None:
            return err(
                ErrorCode.NEO4J_NOT_CONFIGURED,
                "NEO4J_URI is not configured. Start the Neo4j Launcher Application, "
                "copy Internal Bolt URI into Project Settings, and restart Solomon.",
            )
        try:
            config.validate_for_ingest()
        except ValueError as exc:
            return err(ErrorCode.NEO4J_NOT_CONFIGURED, str(exc))

        parsed_columns = [
            c if isinstance(c, ColumnGraphInput) else ColumnGraphInput.model_validate(c)
            for c in columns
        ]
        payload = IngestionGraphPayload(
            catalog=catalog,
            schema=schema,
            table=table,
            columns=[
                ColumnGraphNode(
                    name=c.name,
                    trino_type=c.trino_type,
                    nullable=c.nullable,
                    role=c.role,
                    description=c.description,
                )
                for c in parsed_columns
            ],
            bucket=bucket,
            key=key,
            format=format,
            sheet=sheet,
            header_row=header_row,
            meta_kv=meta_kv or [],
            row_count_hint=row_count_hint,
        )

        loader = IngestionGraphLoader(
            uri=config.uri,
            username=config.username,
            password=config.password,
        )
        try:
            counts = loader.ingest(payload)
        except ValueError as exc:
            return err(ErrorCode.NEO4J_CONNECT_FAILED, str(exc))
        except Exception as exc:  # noqa: BLE001
            _logger.error("neo4j_graph_load.failed", error=str(exc))
            return err(ErrorCode.NEO4J_LOAD_FAILED, f"Neo4j graph load failed: {exc}")
        finally:
            loader.close()

        return ok(
            {
                "dataset_id": payload.dataset_id,
                "source_id": payload.source_id,
                "neo4j_uri": loader._uri,
                "counts": counts,
            }
        )
