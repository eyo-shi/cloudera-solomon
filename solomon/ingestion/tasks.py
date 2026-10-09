"""Ingestion Crew の Task 定義 (Sequential)。

各 Task は前タスクの出力を ``context=[prev_task]`` で受け取り、
:class:`pydantic.BaseModel` を ``output_json`` に指定して LLM が JSON を返す
ことを強制する。副作用のあるタスク (CREATE, Git commit) は
``max_retries=0``、LLM 依存タスクは 1 に設定。

タスク順序:

  1. locate_s3_object_task
  2. sniff_format_task              (未対応形式で早期終了)
  3. extract_dataframe_task
  4. propose_schema_and_name_task
  5. check_conflict_and_permissions_task  (guardrail)
  6. create_iceberg_table_task
  7. load_neo4j_graph_task
  8. draft_ossie_task
  9. index_opensearch_task
  10. wrap_up_task
"""
from __future__ import annotations

from typing import Any, Optional

from solomon.ingestion.models import (
    ConflictAndPermissionsResult,
    CreateIcebergTableResult,
    LoadIcebergDataResult,
    DraftOssieResult,
    IndexOpenSearchResult,
    LoadNeo4jGraphResult,
    ExtractDataFrameResult,
    IngestionReport,
    LocateS3ObjectResult,
    ProposeSchemaAndNameResult,
    SniffFormatResult,
)

try:
    from crewai import Task  # type: ignore
except Exception:  # pragma: no cover
    class Task:  # type: ignore[no-redef]
        """crewai.Task のスタブ。属性を保持するだけ。"""

        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)


# ------------------------------------------------------------------ #
# 1. locate_s3_object_task
# ------------------------------------------------------------------ #
def make_locate_s3_object_task(agent: Any) -> Task:
    return Task(
        description=(
            "ユーザー指示の S3 パス (bucket={bucket}, key={key}) にオブジェクトが"
            "実在するか確認し、size / content_type / last_modified を構造化"
            "して返せ。存在しなければ error_code=S3_NOT_FOUND、権限エラーは"
            "S3_ACCESS_DENIED として exists=false で返す。"
        ),
        expected_output=(
            "LocateS3ObjectResult の JSON。bucket, key, size, content_type, "
            "last_modified, exists を含む。"
        ),
        agent=agent,
        output_json=LocateS3ObjectResult,
        max_retries=1,
    )


# ------------------------------------------------------------------ #
# 2. sniff_format_task
# ------------------------------------------------------------------ #
def make_sniff_format_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "前段で確定した S3 オブジェクト (bucket={bucket}, key={key}) の"
            "フォーマットを判定せよ。"
            "手順: (a) S3GetRangeTool で bucket={bucket}, key={key} の先頭 1MB"
            " を取り、MagicByteTool で format を確定。"
            " (b) csv/tsv なら CSVSnifferTool に必ず bucket={bucket}, "
            "key={key} を渡して encoding と delimiter を確定"
            " (content_b64 を LLM が改変しないよう S3 直読みを使う)。"
            " (b2) J5 完検テキスト (VERSION/KIBAN/DATE メタ行 + 測定表) なら"
            " KankenSniffTool で format=kanken, source_encoding, header_row,"
            " meta_kv を確定する (Shift-JIS 自動デコード)。"
            " (c) xlsx/xls なら ExcelHeaderDetectTool で header_row と sheet"
            " を確定。 (d) parquet なら ParquetMetaTool に bucket={bucket}, "
            "key={key} を渡してスキーマを確認。"
            "判定不能なら supported=false + reason を返し、以降のタスクは"
            "実行しない。"
        ),
        expected_output=(
            "SniffFormatResult の JSON。format, encoding, source_encoding, "
            "delimiter, sheet, header_row, meta_kv, supported, reason を含む。"
        ),
        agent=agent,
        context=context,
        output_json=SniffFormatResult,
        max_retries=1,
    )


# ------------------------------------------------------------------ #
# 3. extract_dataframe_task
# ------------------------------------------------------------------ #
def make_extract_dataframe_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "DataFramePreviewTool を使って bucket={bucket}, key={key} から"
            "先頭 200 行を DataFrame として読み込み、列ごとにサンプル値 50 個"
            "と preview_rows を返せ。bucket/key に unknown や placeholder を"
            "使ってはいけない (Crew inputs の値をそのまま渡す)。"
            "SniffFormat の encoding / delimiter / sheet / header_row を"
            "そのまま渡すこと。列名の空白は除去し、NaN は None に置換する。"
        ),
        expected_output=(
            "ExtractDataFrameResult の JSON。columns[{name, sample_values}], "
            "preview_rows, row_count_preview, full_row_count_hint を含む。"
        ),
        agent=agent,
        context=context,
        output_json=ExtractDataFrameResult,
        max_retries=2,
    )


# ------------------------------------------------------------------ #
# 4. propose_schema_and_name_task
# ------------------------------------------------------------------ #
def make_propose_schema_and_name_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "サンプル値から各カラムの Trino 型を TypeInferTool で推定し、"
            "NameProposerTool で英小文字 + アンダースコアのテーブル名候補を"
            "作れ。Crew inputs の proposed_table_name が空でなければ、"
            "それを proposed_table_name として採用し NameProposerTool は"
            "使わない。Trino catalog は必ず Crew inputs の {catalog} "
            "(Iceberg カタログ。ossie は semantic YAML 用語であり Trino catalog "
            "名ではない) を catalog フィールドにセットする。target_schema "
            "(=Trino スキーマ) はユーザー指定の {target_schema} を使う。"
            "SimilarTableSearchTool で命名衝突と"
            "類似データセットを検索し、exact_conflicts と similar_tables に"
            "積め。role (dimension/measure/time) は数値集計系を measure、"
            "date/timestamp を time、それ以外を dimension として分類する。"
        ),
        expected_output=(
            "ProposeSchemaAndNameResult の JSON。catalog, target_schema, "
            "proposed_table_name, columns[{name, trino_type, nullable, role}],"
            " partitioning, similar_tables, exact_conflicts を含む。"
        ),
        agent=agent,
        context=context,
        output_json=ProposeSchemaAndNameResult,
        max_retries=1,
    )


# ------------------------------------------------------------------ #
# 5. check_conflict_and_permissions_task  (guardrail)
# ------------------------------------------------------------------ #
def make_check_conflict_and_permissions_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "propose_schema_and_name の結果を受け、TableExistsTool で最終的な"
            "衝突チェックと、TrinoMetaTool で CREATE 権限確認を行え。"
            "両 Tool には必ず catalog (= Crew inputs の {catalog} または propose "
            "の catalog。ossie カタログは使わない), schema (= propose の "
            "target_schema), table (= propose の proposed_table_name) を渡すこと。"
            "schema 引数は必須 (target_schema を schema にマップして渡す)。"
            "衝突がある (かつ overwrite=false) 場合は has_conflict=true と"
            "error_code=SCHEMA_NAME_CONFLICT を、CREATE 不可なら"
            " has_create_priv=false と error_code=PERM_CREATE_DENIED を返せ。"
            "どちらも問題ないときのみ後続タスクに進める (Crew.ai の guardrail)。"
        ),
        expected_output=(
            "ConflictAndPermissionsResult の JSON。has_conflict, "
            "has_create_priv, resolved_table, error_code, message を含む。"
        ),
        agent=agent,
        context=context,
        output_json=ConflictAndPermissionsResult,
        max_retries=0,
    )


# ------------------------------------------------------------------ #
# 6. create_iceberg_table_task  (副作用あり: max_retries=0)
# ------------------------------------------------------------------ #
def make_create_iceberg_table_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "check_conflict_and_permissions が通っている前提で、"
            "IcebergCreateTableTool に catalog / target_schema / "
            "resolved_table / columns / partitioning を渡し、Iceberg "
            "テーブルを作成せよ。DDL は Tool 内で組み立てられるので、"
            "Agent が手で SQL を書いてはいけない。Tool が返した "
            "fq_table_name / ddl / column_count を CreateIcebergTableResult "
            "JSON としてそのまま Task 出力にコピーすること (空行のみ禁止)。"
            "副作用ありのため max_retries=0。エラーはそのまま返す (再試行しない)。"
        ),
        expected_output=(
            "CreateIcebergTableResult の JSON。fq_table_name, ddl, column_count"
            " を含む。"
        ),
        agent=agent,
        context=context,
        output_json=CreateIcebergTableResult,
        max_retries=0,
        guardrail_max_retries=0,
    )


# ------------------------------------------------------------------ #
# 7. load_iceberg_data_task  (副作用あり: max_retries=0)
# ------------------------------------------------------------------ #
def make_load_iceberg_data_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "create_iceberg_table 完了後、IcebergLoadDataTool で S3 ソースの"
            "行データを作成済みテーブルへ INSERT せよ。bucket={bucket}, "
            "key={key} と sniff_format の format / encoding / delimiter / "
            "header_row を渡す。propose_schema の target_schema と "
            "resolved_table (= proposed_table_name) を schema / table に使う。"
            "kanken 形式では Shift-JIS デコードとメタ行スキップは Tool 内で"
            "自動処理される。副作用ありのため max_retries=0。"
        ),
        expected_output=(
            "LoadIcebergDataResult の JSON。fq_table_name, inserted_rows, "
            "column_count, source_format を含む。"
        ),
        agent=agent,
        context=context,
        output_json=LoadIcebergDataResult,
        max_retries=0,
    )


# ------------------------------------------------------------------ #
# 8. load_neo4j_graph_task  (副作用あり: max_retries=0)
# ------------------------------------------------------------------ #
def make_load_neo4j_graph_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "load_iceberg_data 完了後、ManufacturingGraphLoadTool で bucket={bucket}, "
            "key={key} と sniff_format の format を渡し、J5 受領データの"
            "製造トレーサビリティグラフ (Board/AssemblyUnit/ValveBody/"
            "TestRecord/MemoryDump/Measurement) を Neo4j に MERGE せよ。"
            "同一 KIBAN のファイルは自動的に同一 Board ノードに接続される。"
            "NEO4J_URI 未設定時は skipped=true, reason を返し、Crew 全体は失敗させない。"
            "副作用ありのため max_retries=0。"
        ),
        expected_output=(
            "LoadNeo4jGraphResult の JSON。data_type, kiban, at_serial, system_id, "
            "system_name, test_record_id, board_id, assembly_unit_id, document_ids, "
            "documents, neo4j_uri, counts, skipped, reason を含む。"
        ),
        agent=agent,
        context=context,
        output_json=LoadNeo4jGraphResult,
        max_retries=0,
    )


# ------------------------------------------------------------------ #
# 9. draft_ossie_task
# ------------------------------------------------------------------ #
def make_draft_ossie_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "作成したテーブルのメタデータから Ossie dataset を組み立て、"
            "OssieWriteTool で semantic/datasets/<catalog>/<schema>/<table>.yaml"
            " に書き出せ (commit=true)。dimensions / measures の判別は"
            " propose_schema_and_name の role をそのまま利用。"
            " create_iceberg_table / load_iceberg_data が失敗している場合は"
            " ossie_write を呼ばず DraftOssieResult を返す: git_status=\"skipped\","
            " skip_reason に理由、yaml_path=\"\", commit_sha=null。"
            " sample_queries は 2-3 件、日本語の自然言語質問と対応する Trino"
            " SQL を提示。ossie_write が OSSIE_YAML_INVALID を返したら"
            " 再試行せず git_status=\"skipped\" + skip_reason で終了する。"
            "副作用ありのため max_retries=0。"
        ),
        expected_output=(
            "DraftOssieResult の JSON。git_status (committed|skipped), fq_name, "
            "yaml_path, commit_sha, skip_reason, dataset を含む。"
        ),
        agent=agent,
        context=context,
        output_json=DraftOssieResult,
        max_retries=0,
    )


# ------------------------------------------------------------------ #
# 10. index_opensearch_task  (副作用あり: max_retries=0)
# ------------------------------------------------------------------ #
def make_index_opensearch_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "draft_ossie 完了後、OpenSearchIndexTool で Ossie dataset と "
            "Neo4j Document 相当のメタデータを外部 OpenSearch (Cloudera Semantic "
            "Search) にインデックスせよ。fq_name, dataset dict, system_id, "
            "documents を前段 (load_neo4j_graph, draft_ossie) から集約して渡す。"
            "OpenSearch 未設定時は skipped=true で返し、Crew 全体は失敗させない。"
            "副作用ありのため max_retries=0。"
        ),
        expected_output=(
            "IndexOpenSearchResult の JSON。fq_name, index, indexed_count, "
            "skipped, reason を含む。"
        ),
        agent=agent,
        context=context,
        output_json=IndexOpenSearchResult,
        max_retries=0,
    )


# ------------------------------------------------------------------ #
# 11. wrap_up_task
# ------------------------------------------------------------------ #
def make_wrap_up_task(agent: Any, context: list[Task]) -> Task:
    return Task(
        description=(
            "これまでのタスク結果を統合し、ユーザーへの最終レポートを"
            "IngestionReport JSON として返せ。summary_markdown には作成した"
            " fq_table_name、inserted_rows、カラム数、Neo4j System/Document 投入結果、"
            "OpenSearch インデックス結果、類似テーブル、Ossie YAML のパスを"
            "日本語で 5-10 行にまとめる。"
        ),
        expected_output=(
            "IngestionReport の JSON。fq_table_name, ddl, column_count, inserted_rows, "
            "ossie_yaml_path, neo4j_dataset_id, neo4j_system_id, neo4j_counts, "
            "opensearch_index, opensearch_indexed_count, similar_tables, "
            "source, summary_markdown を含む。"
        ),
        agent=agent,
        context=context,
        output_json=IngestionReport,
        max_retries=1,
    )


# ------------------------------------------------------------------ #
# guardrail helper
# ------------------------------------------------------------------ #
def create_iceberg_guardrail(output: Any) -> tuple[bool, Optional[str]]:
    """CREATE タスク出力を Trino 上の存在確認で検証する (LLM の成功ハルシネーション防止)。"""
    from solomon.ingestion.create_table import (
        execute_create_iceberg_from_proposal,
        synthesize_create_result_if_table_exists,
    )
    from solomon.ingestion.pipeline_context import get_last_check, get_last_propose
    from solomon.tools.iceberg import TableExistsTool
    from solomon.transport.guardrail import guardrail_pass_model, parse_guardrail_model

    result, err_msg = parse_guardrail_model(output, CreateIcebergTableResult)
    if result is None:
        result = _create_result_from_tool_payload(output)
    if result is None:
        propose = get_last_propose()
        check = get_last_check()
        if propose and check and not check.has_conflict and check.has_create_priv:
            parts = check.resolved_table.split(".")
            if len(parts) == 3:
                catalog, schema, table = parts
                from solomon.transport.trino_catalog import resolve_trino_catalog

                catalog = resolve_trino_catalog(catalog)
                exists = TableExistsTool()._run(
                    catalog=catalog, schema=schema, table=table
                )
                if exists.get("status") == "ok" and exists.get("exists"):
                    result = synthesize_create_result_if_table_exists(propose, check)
                else:
                    recovered = execute_create_iceberg_from_proposal(propose, check)
                    if isinstance(recovered, CreateIcebergTableResult):
                        result = recovered
                    elif isinstance(recovered, dict):
                        msg = recovered.get("message") or err_msg
                        code = recovered.get("error_code") or "TRINO_DDL_FAILED"
                        return False, f"Iceberg テーブル作成に失敗 ({code}): {msg}"
    if result is None:
        return False, err_msg or (
            "guardrail: CreateIcebergTableResult を取得できません。"
            " iceberg_create_table の戻り JSON をそのまま Task 出力にしてください。"
        )
    if not (result.ddl or "").strip():
        return False, (
            "IcebergCreateTableTool が DDL を返していません。"
            "Tool の error_code / message をそのまま Task 出力に反映してください。"
        )
    parts = result.fq_table_name.split(".")
    if len(parts) != 3:
        return False, f"Invalid fq_table_name: {result.fq_table_name!r}"
    catalog, schema, table = parts
    from solomon.transport.trino_catalog import resolve_trino_catalog

    catalog = resolve_trino_catalog(catalog)
    resolved_fq = f"{catalog}.{schema}.{table}"
    if resolved_fq != result.fq_table_name:
        result = result.model_copy(update={"fq_table_name": resolved_fq})
    check = TableExistsTool()._run(catalog=catalog, schema=schema, table=table)
    if check.get("status") == "ok" and check.get("exists"):
        return guardrail_pass_model(result)
    detail = check.get("message") or "Table does not exist in Trino."
    code = check.get("error_code") or "TRINO_DDL_FAILED"
    return False, (
        f"Iceberg テーブル {resolved_fq} の作成を確認できません "
        f"({code}): {detail}"
    )


def _create_result_from_tool_payload(output: Any) -> Optional[CreateIcebergTableResult]:
    """Agent が Tool の ok dict をそのまま返した場合の救済。"""
    from solomon.transport.guardrail import unwrap_task_output

    unwrapped = unwrap_task_output(output)
    if not isinstance(unwrapped, dict):
        return None
    if unwrapped.get("status") != "ok":
        return None
    ddl = str(unwrapped.get("ddl") or "")
    fq = str(unwrapped.get("fq_table_name") or "")
    if not fq or not ddl.strip():
        return None
    try:
        column_count = int(unwrapped.get("column_count") or 0)
    except (TypeError, ValueError):
        column_count = 0
    if column_count <= 0:
        return None
    return CreateIcebergTableResult(
        fq_table_name=fq,
        ddl=ddl,
        column_count=column_count,
    )


def conflict_permissions_guardrail(
    output: Any,
) -> tuple[bool, Optional[str]]:
    """`check_conflict_and_permissions_task` の結果を検査するガードレール。

    Crew.ai の Task には ``guardrail`` パラメータがあり、``(ok, feedback)``
    を返す関数を受け取る。ok=False で Crew は次タスクに進まず停止する。
    """
    from solomon.ingestion.permissions import verify_create_gate_from_fq
    from solomon.transport.guardrail import guardrail_pass_model, parse_guardrail_model

    result, err_msg = parse_guardrail_model(output, ConflictAndPermissionsResult)
    if result is None:
        return False, err_msg

    verified = verify_create_gate_from_fq(result.resolved_table)
    if verified is not None:
        result = verified

    if result.has_conflict:
        return False, (
            f"Table name conflict for {result.resolved_table!r}: "
            f"{result.message or 'already exists'}. Ask the user for another name."
        )
    if not result.has_create_priv:
        return False, (
            f"CREATE permission denied on {result.resolved_table!r}: "
            f"{result.message or 'contact the workspace admin'}."
        )
    return guardrail_pass_model(result)


__all__ = [
    "make_locate_s3_object_task",
    "make_sniff_format_task",
    "make_extract_dataframe_task",
    "make_propose_schema_and_name_task",
    "make_check_conflict_and_permissions_task",
    "make_create_iceberg_table_task",
    "make_load_iceberg_data_task",
    "make_load_neo4j_graph_task",
    "make_draft_ossie_task",
    "make_index_opensearch_task",
    "make_wrap_up_task",
    "create_iceberg_guardrail",
    "conflict_permissions_guardrail",
]
