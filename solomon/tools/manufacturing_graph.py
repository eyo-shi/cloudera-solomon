"""J5 受領データ向け製造トレーサビリティ Neo4j ロード Tool。"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from solomon.graph.config import get_neo4j_config
from solomon.graph.manufacturing.extract import (
    build_payload_from_bytes,
    meta_kv_dict_to_list,
)
from solomon.graph.manufacturing.loader import ManufacturingGraphLoader
from solomon.graph.manufacturing.models import PRODUCT_PROGRAM_ID, PRODUCT_PROGRAM_NAME
from solomon.tools._s3_client import map_s3_error, s3_client_for_user
from solomon.transport.errors import ErrorCode, err, ok
from solomon.transport.logging import get_logger
from solomon.transport.tool_base import BaseSolomonTool
from solomon.transport.user_context import UserContext

_logger = get_logger(__name__)


class ManufacturingGraphLoadArgs(BaseModel):
    bucket: str
    key: str
    format: str = Field("", description="sniff 結果 (kanken / csv / text 等)")


class ManufacturingGraphLoadTool(BaseSolomonTool):
    """4 種類の受領データから製造トレーサビリティグラフを Neo4j に MERGE する。

    ノード: ProductProgram, ValveBody, Board, AssemblyUnit, TestRecord,
            MemoryDump, DecodedField, Measurement, SourceFile

    同一 KIBAN / A/T機番 で複数ファイルを取り込むとグラフが自動的に接続される。
    """

    name: str = "manufacturing_graph_load"
    description: str = (
        "Load J5 received manufacturing data (VB test, main ID dump, kanken, "
        "shukken ID) into Neo4j as a traceability graph. Detects file type from "
        "S3 key and content, decodes Shift-JIS when needed, and MERGEs nodes "
        "linked by KIBAN and AT serial. Call after Iceberg table load."
    )
    args_schema: type[BaseModel] = ManufacturingGraphLoadArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        bucket: str,
        key: str,
        format: str = "",
        **_: Any,
    ) -> dict[str, Any]:
        config = get_neo4j_config()
        if config is None:
            return err(
                ErrorCode.NEO4J_NOT_CONFIGURED,
                "NEO4J_URI is not configured. Start Neo4j Launcher and restart Solomon.",
            )
        try:
            config.validate_for_ingest()
        except ValueError as exc:
            return err(ErrorCode.NEO4J_NOT_CONFIGURED, str(exc))

        client = s3_client_for_user(user_ctx)
        if isinstance(client, dict):
            return client
        try:
            resp = client.get_object(Bucket=bucket, Key=key)
            body: bytes = resp["Body"].read()
        except Exception as e:  # noqa: BLE001
            return map_s3_error(e, bucket, key)

        try:
            payload = build_payload_from_bytes(
                bucket=bucket,
                key=key,
                body=body,
                format_hint=format,
            )
        except Exception as exc:  # noqa: BLE001
            return err(ErrorCode.FORMAT_CORRUPT, f"manufacturing extract failed: {exc}")

        loader = ManufacturingGraphLoader(
            uri=config.uri,
            username=config.username,
            password=config.password,
        )
        try:
            counts = loader.ingest(payload)
        except ValueError as exc:
            return err(ErrorCode.NEO4J_LOAD_FAILED, str(exc))
        except Exception as exc:  # noqa: BLE001
            _logger.error("manufacturing_graph_load.failed", error=str(exc))
            return err(ErrorCode.NEO4J_LOAD_FAILED, f"Neo4j manufacturing load failed: {exc}")
        finally:
            loader.close()

        meta_list = meta_kv_dict_to_list(payload.meta)
        return ok(
            {
                "data_type": payload.data_type,
                "kiban": payload.kiban,
                "at_serial": payload.at_serial,
                "customer_part_no": payload.customer_part_no,
                "system_id": PRODUCT_PROGRAM_ID,
                "system_name": PRODUCT_PROGRAM_NAME,
                "test_record_id": payload.test_record_id,
                "board_id": payload.board_id,
                "assembly_unit_id": payload.assembly_id,
                "dump_field_count": len(payload.dump_fields),
                "dump_fields_preview": [
                    {
                        "address": field.address_hex,
                        "label": field.label,
                        "value": field.value,
                    }
                    for field in payload.dump_fields[:8]
                ],
                "meta_kv": meta_list,
                "document_ids": [f"doc:source:{payload.source_id}"],
                "documents": [
                    {
                        "id": f"doc:source:{payload.source_id}",
                        "title": key.rsplit("/", 1)[-1],
                        "doc_type": payload.data_type,
                        "path": payload.source_id,
                        "content_preview": (
                            f"KIBAN={payload.kiban} AT={payload.at_serial} "
                            f"type={payload.data_type}"
                        ),
                    }
                ],
                "neo4j_uri": loader._uri,
                "counts": counts,
            }
        )


__all__ = ["ManufacturingGraphLoadTool"]
