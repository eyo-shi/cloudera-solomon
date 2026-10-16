"""CrewAI Tool 実装群 (S3 / Trino / Iceberg / Format 判定 / Ossie / DataFrame /
Router / CDV / Viz)。

公開 Tool は :class:`solomon.transport.tool_base.BaseSolomonTool` を継承し、
``requires_auth=True`` のものは Knox JWT / STS 資格情報が必須。

再エクスポート:
  S3:         :class:`S3ListTool`, :class:`S3HeadTool`, :class:`S3GetRangeTool`
  Trino:      :class:`TrinoQueryTool`, :class:`TrinoDDLTool`, :class:`TrinoMetaTool`
  Iceberg:    :class:`TableExistsTool`, :class:`IcebergCreateTableTool`
  Format:     :class:`MagicByteTool`, :class:`CSVSnifferTool`, :class:`ParquetMetaTool`
  Excel:      :class:`ExcelHeaderDetectTool`, :class:`ExcelHeaderValidateTool`
  Schema:     :class:`TypeInferTool`, :class:`NameProposerTool`
  DataFrame:  :class:`DataFramePreviewTool`
  Ossie:      :class:`OssieReadTool`, :class:`OssieWriteTool`, :class:`OssieSearchTool`,
              :class:`SimilarTableSearchTool`
  Router:     :class:`EntityMemoryReadTool`, :class:`AnalyticsKickoffTool`
  CDV:        :class:`CDVStartupCheckTool`, :class:`CDVDatasetTool`,
              :class:`CDVVisualTool`, :class:`CDVDashboardTool`
  Viz:        :class:`VizHeuristicTool`
  Neo4j:      :class:`Neo4jGraphQueryTool` (読み取り専用)
  OpenSearch: :class:`OpenSearchKeywordSearchTool`, :class:`OpenSearchVectorSearchTool`,
              :class:`OpenSearchHybridSearchTool`, :class:`OpenSearchPingTool`
  RAG:        :class:`Text2SQLTool`
"""
from solomon.router.tools import AnalyticsKickoffTool, EntityMemoryReadTool
from solomon.tools.cdv import (
    CDVDashboardTool,
    CDVDatasetTool,
    CDVStartupCheckTool,
    CDVVisualTool,
)
from solomon.tools.dataframe import DataFramePreviewTool
from solomon.tools.excel import ExcelHeaderDetectTool, ExcelHeaderValidateTool
from solomon.tools.format import (
    CSVSnifferTool,
    KankenSniffTool,
    MagicByteTool,
    ParquetMetaTool,
)
from solomon.tools.iceberg import IcebergCreateTableTool, TableExistsTool
from solomon.tools.ossie import (
    OssieReadTool,
    OssieSearchTool,
    OssieWriteTool,
    SimilarTableSearchTool,
)
from solomon.tools.s3 import S3GetRangeTool, S3HeadTool, S3ListTool
from solomon.tools.schema import NameProposerTool, TypeInferTool
from solomon.tools.neo4j_query import Neo4jGraphQueryTool
from solomon.tools.opensearch import (
    OpenSearchHybridSearchTool,
    OpenSearchKeywordSearchTool,
    OpenSearchPingTool,
    OpenSearchVectorSearchTool,
)
from solomon.tools.text2sql import Text2SQLTool
from solomon.tools.trino import TrinoDDLTool, TrinoMetaTool, TrinoQueryTool
from solomon.tools.viz import VizHeuristicTool

__all__ = [
    # s3
    "S3ListTool",
    "S3HeadTool",
    "S3GetRangeTool",
    # trino
    "TrinoQueryTool",
    "TrinoDDLTool",
    "TrinoMetaTool",
    # iceberg
    "TableExistsTool",
    "IcebergCreateTableTool",
    # format
    "MagicByteTool",
    "CSVSnifferTool",
    "KankenSniffTool",
    "ParquetMetaTool",
    # excel
    "ExcelHeaderDetectTool",
    "ExcelHeaderValidateTool",
    # schema
    "TypeInferTool",
    "NameProposerTool",
    # dataframe
    "DataFramePreviewTool",
    # ossie
    "OssieReadTool",
    "OssieWriteTool",
    "OssieSearchTool",
    "SimilarTableSearchTool",
    # router
    "EntityMemoryReadTool",
    "AnalyticsKickoffTool",
    # cdv
    "CDVStartupCheckTool",
    "CDVDatasetTool",
    "CDVVisualTool",
    "CDVDashboardTool",
    # viz
    "VizHeuristicTool",
    # neo4j
    "Neo4jGraphQueryTool",
    # opensearch (external Data Hub)
    "OpenSearchKeywordSearchTool",
    "OpenSearchVectorSearchTool",
    "OpenSearchHybridSearchTool",
    "OpenSearchPingTool",
    # rag
    "Text2SQLTool",
]
