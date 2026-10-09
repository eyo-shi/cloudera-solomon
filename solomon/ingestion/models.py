"""Ingestion Crew の Task 出力スキーマ (Pydantic v2)。

各 Task の ``output_json`` に指定することで、LLM が JSON でない自由記述を
返した場合に Crew.ai が自動で再要求してくれる。Task 間の受け渡し
(``context=[prev_task]``) はこの型を経由する。

タスク → 型の対応:

  locate_s3_object_task            -> LocateS3ObjectResult
  sniff_format_task                -> SniffFormatResult
  extract_dataframe_task           -> ExtractDataFrameResult
  propose_schema_and_name_task     -> ProposeSchemaAndNameResult
  check_conflict_and_permissions_task -> ConflictAndPermissionsResult
  create_iceberg_table_task        -> CreateIcebergTableResult
  load_neo4j_graph_task            -> LoadNeo4jGraphResult
  draft_ossie_task                 -> DraftOssieResult
  index_opensearch_task            -> IndexOpenSearchResult
  wrap_up_task                     -> IngestionReport
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ------------------------------------------------------------------ #
# 1. locate_s3_object
# ------------------------------------------------------------------ #
class LocateS3ObjectResult(BaseModel):
    """S3 上のオブジェクトの物理情報。"""

    bucket: str
    key: str
    size: int
    content_type: Optional[str] = None
    last_modified: Optional[str] = None
    exists: bool = True


# ------------------------------------------------------------------ #
# 2. sniff_format
# ------------------------------------------------------------------ #
class SniffFormatResult(BaseModel):
    """フォーマット判定結果 (MagicByte / CSVSniffer / ExcelHeaderDetect の集約)。"""

    format: str = Field(
        ...,
        description="csv / tsv / xlsx / xls / parquet / json / kanken",
    )
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    encoding: Optional[str] = None  # csv/tsv / kanken 用
    source_encoding: Optional[str] = Field(
        None, description="kanken 等の元ファイル文字コード (例: cp932)"
    )
    delimiter: Optional[str] = None  # csv/tsv 用
    sheet: Optional[str] = None  # xlsx/xls 用
    header_row: Optional[int] = Field(
        None, description="0-indexed. xlsx / kanken / csv(メタ行スキップ) で使用"
    )
    meta_kv: dict[str, str] = Field(
        default_factory=dict, description="kanken / Excel のメタ key/value"
    )
    supported: bool = True
    reason: Optional[str] = None  # supported=False のときの説明


# ------------------------------------------------------------------ #
# 3. extract_dataframe
# ------------------------------------------------------------------ #
class ColumnSample(BaseModel):
    name: str
    sample_values: list[Any] = Field(default_factory=list)


class ExtractDataFrameResult(BaseModel):
    """DataFramePreview の生の結果 + 次ステップに渡す最小情報。"""

    columns: list[ColumnSample]
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count_preview: int
    full_row_count_hint: Optional[int] = None


# ------------------------------------------------------------------ #
# 4. propose_schema_and_name
# ------------------------------------------------------------------ #
class ColumnProposal(BaseModel):
    name: str
    trino_type: str
    nullable: bool = True
    role: str = Field("dimension", description="dimension / measure / time")
    description: Optional[str] = None


class ProposeSchemaAndNameResult(BaseModel):
    """スキーマ + テーブル名の提案。命名衝突検索の結果を同梱。"""

    catalog: str = "iceberg"
    target_schema: str

    @field_validator("catalog", mode="before")
    @classmethod
    def _normalize_catalog(cls, value: Any) -> str:
        from solomon.transport.trino_catalog import resolve_trino_catalog

        if value is None:
            return resolve_trino_catalog(None)
        return resolve_trino_catalog(str(value))
    proposed_table_name: str
    columns: list[ColumnProposal]
    partitioning: list[str] = Field(default_factory=list)
    similar_tables: list[dict[str, Any]] = Field(default_factory=list)
    exact_conflicts: list[dict[str, Any]] = Field(default_factory=list)


# ------------------------------------------------------------------ #
# 5. check_conflict_and_permissions  (guardrail)
# ------------------------------------------------------------------ #
class ConflictAndPermissionsResult(BaseModel):
    """CREATE 前の最終ゲート。

    * ``has_conflict=True`` なら Crew を止めて呼び出し側に別名を問い合わせる
    * ``has_create_priv=False`` なら Crew を止めて権限エラーを返す
    """

    has_conflict: bool
    has_create_priv: bool
    resolved_table: str
    error_code: Optional[str] = None
    message: Optional[str] = None

    @model_validator(mode="after")
    def _normalize_resolved_table(self) -> ConflictAndPermissionsResult:
        from solomon.transport.trino_catalog import resolve_trino_catalog

        parts = self.resolved_table.split(".")
        if len(parts) != 3:
            return self
        catalog, schema, table = parts
        fixed = resolve_trino_catalog(catalog)
        if fixed != catalog:
            self.resolved_table = f"{fixed}.{schema}.{table}"
        return self


# ------------------------------------------------------------------ #
# 6. create_iceberg_table
# ------------------------------------------------------------------ #
class CreateIcebergTableResult(BaseModel):
    fq_table_name: str
    ddl: str
    column_count: int


class LoadIcebergDataResult(BaseModel):
    fq_table_name: str
    inserted_rows: int
    column_count: int
    source_format: str


# ------------------------------------------------------------------ #
# 7. load_neo4j_graph
# ------------------------------------------------------------------ #
class LoadNeo4jGraphResult(BaseModel):
    data_type: Optional[str] = None
    kiban: Optional[str] = None
    at_serial: Optional[str] = None
    customer_part_no: Optional[str] = None
    dataset_id: Optional[str] = None
    source_id: Optional[str] = None
    system_id: Optional[str] = None
    system_name: Optional[str] = None
    test_record_id: Optional[str] = None
    board_id: Optional[str] = None
    assembly_unit_id: Optional[str] = None
    document_ids: list[str] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    neo4j_uri: Optional[str] = None
    counts: dict[str, int] = Field(default_factory=dict)
    skipped: bool = False
    reason: Optional[str] = None


# ------------------------------------------------------------------ #
# 8. draft_ossie
# ------------------------------------------------------------------ #
class DraftOssieResult(BaseModel):
    fq_name: str
    yaml_path: str
    git_status: str  # "committed" / "skipped"
    commit_sha: Optional[str] = None
    dataset: dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------ #
# 9. index_opensearch
# ------------------------------------------------------------------ #
class IndexOpenSearchResult(BaseModel):
    fq_name: str
    index: Optional[str] = None
    indexed_count: int = 0
    skipped: bool = False
    reason: Optional[str] = None


# ------------------------------------------------------------------ #
# 10. wrap_up
# ------------------------------------------------------------------ #
class IngestionReport(BaseModel):
    """ユーザーに返す最終レポート (Markdown はレンダー時に組み立てる)。"""

    model_config = ConfigDict(extra="ignore")

    fq_table_name: str
    ddl: str
    column_count: int
    inserted_rows: int = 0
    ossie_yaml_path: str
    neo4j_dataset_id: Optional[str] = None
    neo4j_system_id: Optional[str] = None
    neo4j_counts: dict[str, int] = Field(default_factory=dict)
    opensearch_index: Optional[str] = None
    opensearch_indexed_count: int = 0
    similar_tables: list[dict[str, Any]] = Field(default_factory=list)
    source: dict[str, Any] = Field(default_factory=dict)
    summary_markdown: str = ""
