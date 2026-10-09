"""Ingestion Crew のタスク順に対応する UI 向け activity ラベル。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class IngestionPhase:
    agent: str
    activity: str
    running_message: str
    done_message: str


# build_ingestion_crew の tasks 配列と同じ順序 (11 件)
INGESTION_PHASES: tuple[IngestionPhase, ...] = (
    IngestionPhase(
        "Ingestion:Locate",
        "Checking S3",
        "Storage（S3）上のファイルを確認しています…",
        "S3 オブジェクトを確認しました",
    ),
    IngestionPhase(
        "Ingestion:Sniff",
        "Detecting format",
        "ファイル形式を判定しています…",
        "ファイル形式を判定しました",
    ),
    IngestionPhase(
        "Ingestion:Extract",
        "Reading sample data",
        "先頭行を読み取り、列サンプルを取得しています…",
        "データプレビューを取得しました",
    ),
    IngestionPhase(
        "Ingestion:Schema",
        "Designing schema",
        "Iceberg 向けスキーマとテーブル名を提案しています…",
        "スキーマ案を作成しました",
    ),
    IngestionPhase(
        "Ingestion:Permissions",
        "Checking permissions",
        "権限と命名衝突を確認しています…",
        "権限・衝突チェックが完了しました",
    ),
    IngestionPhase(
        "Ingestion:CreateTable",
        "Creating Iceberg table",
        "Trino で Iceberg テーブルを作成しています…",
        "Iceberg テーブルを作成しました",
    ),
    IngestionPhase(
        "Ingestion:Iceberg",
        "Importing to Iceberg",
        "S3 ソースから Iceberg テーブルへデータを投入しています…",
        "Iceberg へのデータ投入が完了しました",
    ),
    IngestionPhase(
        "Ingestion:Graph",
        "Updating knowledge graph",
        "Neo4j ナレッジグラフを更新しています…",
        "ナレッジグラフを更新しました",
    ),
    IngestionPhase(
        "Ingestion:Ossie",
        "Drafting semantic layer",
        "Ossie セマンティック定義を作成しています…",
        "Ossie 定義を作成しました",
    ),
    IngestionPhase(
        "Ingestion:Search",
        "Indexing OpenSearch",
        "OpenSearch にドキュメントを索引付けしています…",
        "OpenSearch の索引付けが完了しました",
    ),
    IngestionPhase(
        "Ingestion:WrapUp",
        "Finalizing report",
        "取り込み結果をまとめています…",
        "レポートを作成しました",
    ),
)


def phase_by_index(index: int) -> Optional[IngestionPhase]:
    if 0 <= index < len(INGESTION_PHASES):
        return INGESTION_PHASES[index]
    return None


def iter_phases() -> Iterator[IngestionPhase]:
    yield from INGESTION_PHASES


__all__ = ["IngestionPhase", "INGESTION_PHASES", "phase_by_index", "iter_phases"]
