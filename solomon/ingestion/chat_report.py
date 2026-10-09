"""取り込み完了後のチャット向けタイムライン Markdown。"""
from __future__ import annotations

from typing import Any, Optional, TypeVar

from pydantic import BaseModel

from solomon.ingestion.models import (
    CreateIcebergTableResult,
    DraftOssieResult,
    IndexOpenSearchResult,
    LoadIcebergDataResult,
    LoadNeo4jGraphResult,
    LocateS3ObjectResult,
    ProposeSchemaAndNameResult,
)

T = TypeVar("T", bound=BaseModel)


def format_duration_seconds(seconds: float) -> str:
    sec = max(0, int(round(seconds)))
    if sec < 60:
        return f"{sec}秒"
    minutes, rem = divmod(sec, 60)
    if minutes < 60:
        return f"{minutes}分{rem}秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}時間{minutes}分{rem}秒"


def _extract_task_model(raw: Any, task_index: int, model_cls: type[T]) -> Optional[T]:
    tasks_output = getattr(raw, "tasks_output", None)
    if not tasks_output:
        return None
    try:
        task_out = tasks_output[task_index]
    except (IndexError, TypeError):
        return None
    if task_out is None:
        return None
    for attr in ("pydantic", "json_dict", "raw"):
        payload = getattr(task_out, attr, None)
        if payload is None:
            continue
        if isinstance(payload, model_cls):
            return payload
        if isinstance(payload, dict):
            try:
                return model_cls.model_validate(payload)
            except Exception:  # noqa: BLE001
                continue
        if isinstance(payload, str):
            try:
                import json

                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    return model_cls.model_validate(parsed)
            except Exception:  # noqa: BLE001
                continue
    return None


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "（集計なし）"
    parts = [f"{label} {n}" for label, n in sorted(counts.items()) if n]
    return "、".join(parts) if parts else "（0 件）"


def format_ingestion_chat_markdown(
    *,
    bucket: str,
    key: str,
    report: dict[str, Any],
    crew_raw: Any = None,
    duration_sec: Optional[float] = None,
) -> str:
    """S3 → Iceberg → Graph → Search の時系列サマリーを Markdown で返す。"""
    s3_uri = f"s3://{bucket}/{key}"
    locate = (
        _extract_task_model(crew_raw, 0, LocateS3ObjectResult)
        if crew_raw is not None
        else None
    )
    propose = _extract_task_model(crew_raw, 3, ProposeSchemaAndNameResult)
    create = _extract_task_model(crew_raw, 5, CreateIcebergTableResult)
    load = _extract_task_model(crew_raw, 6, LoadIcebergDataResult)
    graph = _extract_task_model(crew_raw, 7, LoadNeo4jGraphResult)
    ossie = _extract_task_model(crew_raw, 8, DraftOssieResult)
    search = _extract_task_model(crew_raw, 9, IndexOpenSearchResult)

    fq = report.get("fq_table_name") or (create.fq_table_name if create else "")
    if not fq and propose:
        fq = f"{propose.catalog}.{propose.target_schema}.{propose.proposed_table_name}"

    lines: list[str] = ["## 取り込み結果", ""]

    # 1. S3
    lines.append("### 1. Storage（S3）")
    lines.append(f"- **配置先**: `{s3_uri}`")
    if locate and locate.exists:
        size = locate.size
        if size >= 1024 * 1024:
            lines.append(f"- オブジェクトサイズ: {size / (1024 * 1024):.2f} MB")
        elif size >= 1024:
            lines.append(f"- オブジェクトサイズ: {size / 1024:.1f} KB")
        else:
            lines.append(f"- オブジェクトサイズ: {size} B")
        if locate.content_type:
            lines.append(f"- Content-Type: {locate.content_type}")
    lines.append("")

    # 2. Iceberg
    lines.append("### 2. Lakehouse（Iceberg）")
    if fq:
        lines.append(f"- **テーブル**: `{fq}`")
    cols = report.get("column_count")
    if cols is None and create:
        cols = create.column_count
    if cols is not None:
        lines.append(f"- カラム数: {cols}")
    inserted = report.get("inserted_rows")
    if load is not None:
        inserted = load.inserted_rows
    if inserted is not None:
        lines.append(f"- 投入行数: **{inserted}**")
    if create and create.ddl:
        ddl_one = " ".join(create.ddl.split())
        if len(ddl_one) > 120:
            ddl_one = ddl_one[:117] + "..."
        lines.append(f"- DDL: `{ddl_one}`")
    if not fq and not inserted:
        lines.append("- （Iceberg への投入は完了しなかったか、レポートに含まれていません）")
    lines.append("")

    # 3. Graph
    lines.append("### 3. ナレッジグラフ（Neo4j）")
    if graph and graph.skipped:
        lines.append(f"- **スキップ**: {graph.reason or 'NEO4J 未設定等'}")
    elif graph:
        if graph.data_type:
            lines.append(f"- データ種別: `{graph.data_type}`")
        hints: list[str] = []
        if graph.kiban:
            hints.append(f"KIBAN `{graph.kiban}`")
        if graph.at_serial:
            hints.append(f"A/T `{graph.at_serial}`")
        if graph.board_id:
            hints.append(f"Board `{graph.board_id}`")
        if graph.test_record_id:
            hints.append(f"TestRecord `{graph.test_record_id}`")
        if hints:
            lines.append("- キー: " + " · ".join(hints))
        counts = graph.counts or report.get("neo4j_counts") or {}
        if counts:
            lines.append(f"- **ノード / リレーション**: {_format_counts(counts)}")
        elif report.get("neo4j_system_id"):
            lines.append(f"- system_id: `{report['neo4j_system_id']}`")
    else:
        neo_counts = report.get("neo4j_counts") or {}
        if neo_counts:
            lines.append(f"- **ノード / リレーション**: {_format_counts(neo_counts)}")
        else:
            lines.append("- （グラフ投入結果はレポートに含まれていません）")
    lines.append("")

    # 4. Search
    lines.append("### 4. セマンティック検索（OpenSearch）")
    if ossie and ossie.git_status == "skipped":
        lines.append(f"- Ossie YAML: スキップ（{ossie.skip_reason or '未作成'}）")
    elif ossie and ossie.yaml_path:
        lines.append(f"- Ossie YAML: `{ossie.yaml_path}`")
    elif report.get("ossie_yaml_path"):
        lines.append(f"- Ossie YAML: `{report['ossie_yaml_path']}`")

    if search and search.skipped:
        lines.append(f"- **インデックス**: スキップ（{search.reason or 'OpenSearch 未設定'}）")
    elif search:
        if search.index:
            lines.append(f"- **インデックス**: `{search.index}`")
        if search.fq_name:
            lines.append(f"- データセット: `{search.fq_name}`")
        lines.append(f"- 登録ドキュメント数: **{search.indexed_count}**")
    else:
        idx = report.get("opensearch_index")
        cnt = report.get("opensearch_indexed_count")
        if idx:
            lines.append(f"- **インデックス**: `{idx}`")
        if cnt is not None:
            lines.append(f"- 登録ドキュメント数: **{cnt}**")
        if not idx and cnt is None:
            lines.append("- （OpenSearch への索引付けはスキップまたは未実行）")
    lines.append("")

    similar = report.get("similar_tables") or []
    if similar:
        lines.append("**類似テーブル（参考）**: ")
        lines.append(
            ", ".join(f"`{s.get('fq_name', s)}`" for s in similar[:3])
        )
        lines.append("")

    summary = (report.get("summary_markdown") or "").strip()
    if summary:
        lines.append("---")
        lines.append(summary)
        lines.append("")

    if duration_sec is not None:
        lines.append(f"**処理時間**: {format_duration_seconds(duration_sec)}")
        lines.append("")

    return "\n".join(lines)


def pipeline_sse_steps(
    *,
    bucket: str,
    key: str,
    report: dict[str, Any],
    crew_raw: Any = None,
) -> list[tuple[str, str, str, str]]:
    """(agent, status, message, activity) — 時系列サマリー用 SSE step。"""
    fq = report.get("fq_table_name", "")
    load = _extract_task_model(crew_raw, 6, LoadIcebergDataResult) if crew_raw else None
    graph = _extract_task_model(crew_raw, 7, LoadNeo4jGraphResult) if crew_raw else None
    search = _extract_task_model(crew_raw, 9, IndexOpenSearchResult) if crew_raw else None

    steps: list[tuple[str, str, str, str]] = []
    steps.append(
        (
            "Ingestion:Locate",
            "done",
            f"`s3://{bucket}/{key}`",
            "Checking S3",
        )
    )
    if fq:
        rows = load.inserted_rows if load else report.get("inserted_rows", "?")
        steps.append(
            (
                "Ingestion:Iceberg",
                "done",
                f"`{fq}` · {rows} 行",
                "Importing to Iceberg",
            )
        )
    if graph and not graph.skipped and graph.counts:
        steps.append(
            (
                "Ingestion:Graph",
                "done",
                _format_counts(graph.counts),
                "Updating knowledge graph",
            )
        )
    elif graph and graph.skipped:
        steps.append(
            (
                "Ingestion:Graph",
                "skipped",
                graph.reason or "skipped",
                "Updating knowledge graph",
            )
        )
    if search and not search.skipped:
        steps.append(
            (
                "Ingestion:Search",
                "done",
                f"`{search.index or 'index'}` · {search.indexed_count} 件",
                "Indexing OpenSearch",
            )
        )
    elif search and search.skipped:
        steps.append(
            (
                "Ingestion:Search",
                "skipped",
                search.reason or "skipped",
                "Indexing OpenSearch",
            )
        )
    return steps


__all__ = [
    "format_duration_seconds",
    "format_ingestion_chat_markdown",
    "pipeline_sse_steps",
]
