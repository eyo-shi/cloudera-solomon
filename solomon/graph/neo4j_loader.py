"""Load ingestion metadata graph into Neo4j."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from neo4j import GraphDatabase

from solomon.graph.neo4j_connect import format_neo4j_connection_help, iter_neo4j_connection_uris

BATCH_SIZE = 200


@dataclass
class ColumnGraphNode:
    name: str
    trino_type: str
    nullable: bool = True
    role: str = "dimension"
    description: str | None = None

    @property
    def id(self) -> str:
        return self.name


@dataclass
class DocumentGraphNode:
    """設計書 / ソースファイル / セマンティックレイヤ等の Document ノード。"""

    id: str
    title: str
    doc_type: str  # source_file | design_doc | semantic_layer | reference
    path: str
    content_preview: str | None = None


@dataclass
class IngestionGraphPayload:
    """Graph payload built from an Iceberg ingestion run."""

    catalog: str
    schema: str
    table: str
    columns: list[ColumnGraphNode]
    bucket: str
    key: str
    format: str
    sheet: str | None = None
    header_row: int | None = None
    meta_kv: list[dict[str, Any]] = field(default_factory=list)
    row_count_hint: int | None = None
    system_name: str = "default"
    system_description: str | None = None
    documents: list[DocumentGraphNode] = field(default_factory=list)

    @property
    def dataset_id(self) -> str:
        return f"{self.catalog}.{self.schema}.{self.table}"

    @property
    def source_id(self) -> str:
        return f"s3://{self.bucket}/{self.key}"

    @property
    def schema_id(self) -> str:
        return f"{self.catalog}.{self.schema}"

    @property
    def system_id(self) -> str:
        from solomon.graph.system import normalize_system_id

        return normalize_system_id(self.system_name)


class IngestionGraphLoader:
    """Write Dataset / Column / SourceFile / System / Document nodes into Neo4j."""

    def __init__(self, uri: str, username: str, password: str) -> None:
        self._configured_uri = uri
        self._uri = uri
        self._username = username
        self._password = password
        self._driver = None

    def _connect(self, uri: str):
        return GraphDatabase.driver(uri, auth=(self._username, self._password))

    def verify_connectivity(self) -> None:
        errors: list[str] = []
        candidates = iter_neo4j_connection_uris(self._configured_uri)
        if not candidates:
            raise ValueError(format_neo4j_connection_help(self._configured_uri, errors))

        for candidate in candidates:
            driver = self._connect(candidate)
            try:
                driver.verify_connectivity()
            except Exception as exc:
                driver.close()
                errors.append(f"  {candidate}: {exc}")
                continue

            if self._driver is not None:
                self._driver.close()
            self._uri = candidate
            self._driver = driver
            return

        raise ValueError(format_neo4j_connection_help(self._configured_uri, errors))

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()

    def ingest(self, payload: IngestionGraphPayload) -> dict[str, int]:
        self.verify_connectivity()
        assert self._driver is not None
        with self._driver.session() as session:
            session.execute_write(self._ensure_constraints)
            session.execute_write(self._delete_dataset, payload.dataset_id)
            session.execute_write(self._create_nodes, payload)
            counts = session.execute_write(self._create_relationships, payload)
        return counts

    @staticmethod
    def _ensure_constraints(tx) -> None:
        for label, prop in (
            ("Dataset", "id"),
            ("Column", "id"),
            ("SourceFile", "id"),
            ("Schema", "id"),
            ("MetadataEntry", "id"),
            ("System", "id"),
            ("Document", "id"),
        ):
            tx.run(
                f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )

    @staticmethod
    def _delete_dataset(tx, dataset_id: str) -> None:
        tx.run(
            """
            MATCH (d:Dataset {id: $dataset_id})
            OPTIONAL MATCH (d)-[:HAS_COLUMN]->(c:Column)
            OPTIONAL MATCH (d)-[:SOURCED_FROM]->(s:SourceFile)
            OPTIONAL MATCH (s)-[:HAS_METADATA]->(m:MetadataEntry)
            DETACH DELETE d, c, s, m
            """,
            dataset_id=dataset_id,
        )

    @staticmethod
    def _create_nodes(tx, payload: IngestionGraphPayload) -> None:
        ingested_at = datetime.now(timezone.utc).isoformat()
        tx.run(
            """
            MERGE (d:Dataset {id: $dataset_id})
            SET d.catalog = $catalog,
                d.schema = $schema,
                d.name = $table,
                d.fq_name = $dataset_id,
                d.column_count = $column_count,
                d.format = $format,
                d.sheet = $sheet,
                d.header_row = $header_row,
                d.row_count_hint = $row_count_hint,
                d.ingested_at = $ingested_at
            """,
            dataset_id=payload.dataset_id,
            catalog=payload.catalog,
            schema=payload.schema,
            table=payload.table,
            column_count=len(payload.columns),
            format=payload.format,
            sheet=payload.sheet,
            header_row=payload.header_row,
            row_count_hint=payload.row_count_hint,
            ingested_at=ingested_at,
        )
        tx.run(
            """
            MERGE (s:Schema {id: $schema_id})
            SET s.catalog = $catalog,
                s.name = $schema
            """,
            schema_id=payload.schema_id,
            catalog=payload.catalog,
            schema=payload.schema,
        )
        tx.run(
            """
            MERGE (f:SourceFile {id: $source_id})
            SET f.bucket = $bucket,
                f.key = $key,
                f.format = $format,
                f.sheet = $sheet,
                f.header_row = $header_row
            """,
            source_id=payload.source_id,
            bucket=payload.bucket,
            key=payload.key,
            format=payload.format,
            sheet=payload.sheet,
            header_row=payload.header_row,
        )
        column_rows = [
            {
                "id": f"{payload.dataset_id}.{col.name}",
                "dataset_id": payload.dataset_id,
                "name": col.name,
                "trino_type": col.trino_type,
                "nullable": col.nullable,
                "role": col.role,
                "description": col.description,
            }
            for col in payload.columns
        ]
        for index in range(0, len(column_rows), BATCH_SIZE):
            chunk = column_rows[index : index + BATCH_SIZE]
            tx.run(
                """
                UNWIND $rows AS row
                MERGE (c:Column {id: row.id})
                SET c.dataset_id = row.dataset_id,
                    c.name = row.name,
                    c.trino_type = row.trino_type,
                    c.nullable = row.nullable,
                    c.role = row.role,
                    c.description = row.description
                """,
                rows=chunk,
            )
        meta_rows = [
            {
                "id": f"{payload.source_id}::{item.get('key', '')}",
                "source_id": payload.source_id,
                "key": str(item.get("key", "")),
                "value": str(item.get("value", "")),
            }
            for item in payload.meta_kv
            if item.get("key")
        ]
        for index in range(0, len(meta_rows), BATCH_SIZE):
            chunk = meta_rows[index : index + BATCH_SIZE]
            tx.run(
                """
                UNWIND $rows AS row
                MERGE (m:MetadataEntry {id: row.id})
                SET m.key = row.key,
                    m.value = row.value,
                    m.source_id = row.source_id
                """,
                rows=chunk,
            )

        tx.run(
            """
            MERGE (sys:System {id: $system_id})
            SET sys.name = $system_name,
                sys.description = $system_description
            """,
            system_id=payload.system_id,
            system_name=payload.system_name,
            system_description=payload.system_description,
        )

        doc_rows = [
            {
                "id": doc.id,
                "title": doc.title,
                "doc_type": doc.doc_type,
                "path": doc.path,
                "content_preview": doc.content_preview,
            }
            for doc in payload.documents
        ]
        for index in range(0, len(doc_rows), BATCH_SIZE):
            chunk = doc_rows[index : index + BATCH_SIZE]
            tx.run(
                """
                UNWIND $rows AS row
                MERGE (doc:Document {id: row.id})
                SET doc.title = row.title,
                    doc.doc_type = row.doc_type,
                    doc.path = row.path,
                    doc.content_preview = row.content_preview
                """,
                rows=chunk,
            )

    @staticmethod
    def _create_relationships(tx, payload: IngestionGraphPayload) -> dict[str, int]:
        tx.run(
            """
            MATCH (d:Dataset {id: $dataset_id})
            MATCH (s:Schema {id: $schema_id})
            MERGE (d)-[:IN_SCHEMA]->(s)
            """,
            dataset_id=payload.dataset_id,
            schema_id=payload.schema_id,
        )
        tx.run(
            """
            MATCH (d:Dataset {id: $dataset_id})
            MATCH (f:SourceFile {id: $source_id})
            MERGE (d)-[:SOURCED_FROM]->(f)
            """,
            dataset_id=payload.dataset_id,
            source_id=payload.source_id,
        )
        tx.run(
            """
            MATCH (d:Dataset {id: $dataset_id})
            MATCH (c:Column {dataset_id: $dataset_id})
            MERGE (d)-[:HAS_COLUMN]->(c)
            """,
            dataset_id=payload.dataset_id,
        )
        result = tx.run(
            """
            MATCH (f:SourceFile {id: $source_id})
            MATCH (m:MetadataEntry {source_id: $source_id})
            MERGE (f)-[:HAS_METADATA]->(m)
            RETURN count(m) AS metadata_count
            """,
            source_id=payload.source_id,
        )
        metadata_count = result.single()["metadata_count"] if payload.meta_kv else 0

        tx.run(
            """
            MATCH (sys:System {id: $system_id})
            MATCH (d:Dataset {id: $dataset_id})
            MERGE (sys)-[:OWNS_DATASET]->(d)
            """,
            system_id=payload.system_id,
            dataset_id=payload.dataset_id,
        )

        doc_rel_count = 0
        for doc in payload.documents:
            tx.run(
                """
                MATCH (sys:System {id: $system_id})
                MATCH (doc:Document {id: $doc_id})
                MERGE (sys)-[:HAS_DOCUMENT]->(doc)
                """,
                system_id=payload.system_id,
                doc_id=doc.id,
            )
            tx.run(
                """
                MATCH (doc:Document {id: $doc_id})
                MATCH (d:Dataset {id: $dataset_id})
                MERGE (doc)-[:REFERENCES_DATASET]->(d)
                """,
                doc_id=doc.id,
                dataset_id=payload.dataset_id,
            )
            doc_rel_count += 2

        return {
            "dataset_nodes": 1,
            "column_nodes": len(payload.columns),
            "source_nodes": 1,
            "schema_nodes": 1,
            "metadata_nodes": metadata_count,
            "system_nodes": 1,
            "document_nodes": len(payload.documents),
            "relationships": 3 + len(payload.columns) + metadata_count + doc_rel_count,
        }
