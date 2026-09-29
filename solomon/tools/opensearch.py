"""OpenSearch Tools — external cluster または internal launcher への接続。

``OPENSEARCH_MODE`` (internal / external) で接続先を切り替える。
Solomon プロセス内では OpenSearch サーバーは起動せず、opensearch-py で接続する。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from solomon.opensearch.client import ping
from solomon.opensearch.indexer import index_graph_documents, index_ossie_dataset
from solomon.opensearch.search import hybrid_search, keyword_search, vector_search
from solomon.transport.config import get_opensearch_config
from solomon.transport.errors import ErrorCode, err, ok
from solomon.transport.tool_base import BaseSolomonTool
from solomon.transport.user_context import UserContext

def _not_configured_msg() -> str:
    from solomon.opensearch.mode import is_internal_opensearch_mode

    if is_internal_opensearch_mode():
        return (
            "OpenSearch is not configured for internal mode. Ensure "
            "opensearch-launcher Application is Running, wait for "
            ".solomon/opensearch_endpoints.json, or set OPENSEARCH_ENDPOINT, "
            "then restart Solomon."
        )
    return (
        "OpenSearch is not configured. Set OPENSEARCH_MODE=external, "
        "provision Semantic Search for AWS on Data Hub, register a Data Connection "
        "(or set OPENSEARCH_ENDPOINT and OPENSEARCH_NAMESPACE), "
        "then restart Solomon."
    )


class OpenSearchKeywordSearchArgs(BaseModel):
    query: str = Field(..., description="自然言語の検索クエリ")
    top_k: int = Field(3, ge=1, le=20)


class OpenSearchKeywordSearchTool(BaseSolomonTool):
    """Data Hub OpenSearch へ BM25 キーワード検索を実行する。"""

    name: str = "opensearch_keyword_search"
    description: str = (
        "Search datasets in the external Cloudera Semantic Search (OpenSearch) "
        "cluster using BM25 keyword matching."
    )
    args_schema: type[BaseModel] = OpenSearchKeywordSearchArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        query: str,
        top_k: int = 3,
        **_: Any,
    ) -> dict[str, Any]:
        config = get_opensearch_config()
        if config is None:
            return err(ErrorCode.OPENSEARCH_NOT_CONFIGURED, _not_configured_msg())
        try:
            results = keyword_search(config, query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            return err(
                ErrorCode.OPENSEARCH_QUERY_FAILED,
                f"OpenSearch keyword search failed: {exc}",
            )
        return ok(
            {
                "query": query,
                "top_k": top_k,
                "index": config.index_name,
                "namespace": config.namespace,
                "connection_name": config.connection_name,
                "results": results,
            }
        )


class OpenSearchVectorSearchArgs(BaseModel):
    query: str = Field(..., description="自然言語の検索クエリ (embedding → k-NN)")
    top_k: int = Field(3, ge=1, le=20)


class OpenSearchVectorSearchTool(BaseSolomonTool):
    """Data Hub OpenSearch へ k-NN ベクトル検索を実行する。"""

    name: str = "opensearch_vector_search"
    description: str = (
        "Search datasets in the external Cloudera Semantic Search (OpenSearch) "
        "cluster using k-NN vector similarity. Requires LLM embedding model."
    )
    args_schema: type[BaseModel] = OpenSearchVectorSearchArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        query: str,
        top_k: int = 3,
        **_: Any,
    ) -> dict[str, Any]:
        config = get_opensearch_config()
        if config is None:
            return err(ErrorCode.OPENSEARCH_NOT_CONFIGURED, _not_configured_msg())
        try:
            results = vector_search(config, query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            return err(
                ErrorCode.OPENSEARCH_QUERY_FAILED,
                f"OpenSearch vector search failed: {exc}",
            )
        return ok(
            {
                "query": query,
                "top_k": top_k,
                "index": config.index_name,
                "namespace": config.namespace,
                "connection_name": config.connection_name,
                "results": results,
            }
        )


class OpenSearchHybridSearchArgs(BaseModel):
    query: str = Field(..., description="自然言語クエリ (BM25 + k-NN Hybrid)")
    top_k: int = Field(5, ge=1, le=20)


class OpenSearchHybridSearchTool(BaseSolomonTool):
    """Data Hub OpenSearch へ Hybrid Search (Keyword + Vector RRF) を実行する。"""

    name: str = "opensearch_hybrid_search"
    description: str = (
        "Search datasets using Hybrid Search (BM25 keyword + k-NN vector with RRF) "
        "in the external Cloudera Semantic Search cluster."
    )
    args_schema: type[BaseModel] = OpenSearchHybridSearchArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        query: str,
        top_k: int = 5,
        **_: Any,
    ) -> dict[str, Any]:
        config = get_opensearch_config()
        if config is None:
            return err(ErrorCode.OPENSEARCH_NOT_CONFIGURED, _not_configured_msg())
        try:
            results = hybrid_search(config, query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            return err(
                ErrorCode.OPENSEARCH_QUERY_FAILED,
                f"OpenSearch hybrid search failed: {exc}",
            )
        return ok(
            {
                "query": query,
                "top_k": top_k,
                "search_mode": "hybrid",
                "index": config.index_name,
                "results": results,
            }
        )


class OpenSearchIndexArgs(BaseModel):
    fq_name: str = Field(..., description="catalog.schema.table")
    dataset: dict[str, Any] = Field(..., description="Ossie dataset dict")
    system_id: Optional[str] = Field(None, description="Neo4j System id")
    documents: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Neo4j Document ノード相当 (id, title, doc_type, path, content_preview)",
    )


class OpenSearchIndexTool(BaseSolomonTool):
    """Ossie dataset と関連 Document を外部 OpenSearch にインデックスする。"""

    name: str = "opensearch_index"
    description: str = (
        "Index an Ossie dataset and optional related documents into the external "
        "Cloudera Semantic Search cluster. Call after ossie_write during ingestion. "
        "Skips gracefully when OpenSearch is not configured."
    )
    args_schema: type[BaseModel] = OpenSearchIndexArgs
    requires_auth: bool = False

    def run(
        self,
        user_ctx: Optional[UserContext],
        fq_name: str,
        dataset: dict[str, Any],
        system_id: Optional[str] = None,
        documents: Optional[list[dict[str, Any]]] = None,
        **_: Any,
    ) -> dict[str, Any]:
        config = get_opensearch_config()
        if config is None:
            return ok(
                {
                    "skipped": True,
                    "reason": "OpenSearch is not configured",
                    "fq_name": fq_name,
                }
            )
        try:
            main = index_ossie_dataset(
                config, fq_name, dataset, system_id=system_id, with_embedding=True
            )
            doc_results: list[dict[str, Any]] = []
            if documents:
                doc_results = index_graph_documents(
                    config,
                    system_id=system_id or "default",
                    dataset_id=fq_name,
                    documents=documents,
                )
        except Exception as exc:  # noqa: BLE001
            return err(
                ErrorCode.OPENSEARCH_INDEX_FAILED,
                f"OpenSearch indexing failed: {exc}",
            )
        return ok(
            {
                "fq_name": fq_name,
                "index": config.index_name,
                "dataset_index": main,
                "document_indexes": doc_results,
                "indexed_count": 1 + len(doc_results),
            }
        )


class OpenSearchPingArgs(BaseModel):
    pass


class OpenSearchPingTool(BaseSolomonTool):
    """外部 OpenSearch クラスタへの接続確認。"""

    name: str = "opensearch_ping"
    description: str = (
        "Check connectivity to the external Cloudera Semantic Search (OpenSearch) "
        "cluster configured via Data Connection or environment variables."
    )
    args_schema: type[BaseModel] = OpenSearchPingArgs
    requires_auth: bool = False

    def run(self, user_ctx: Optional[UserContext], **_: Any) -> dict[str, Any]:
        config = get_opensearch_config()
        if config is None:
            return err(ErrorCode.OPENSEARCH_NOT_CONFIGURED, _not_configured_msg())
        reachable = ping(config)
        if not reachable:
            return err(
                ErrorCode.OPENSEARCH_CONNECT_FAILED,
                f"Cannot reach OpenSearch at {config.scheme}://{config.host}:{config.port}",
            )
        return ok(
            {
                "host": config.host,
                "port": config.port,
                "index": config.index_name,
                "namespace": config.namespace,
                "connection_name": config.connection_name,
            }
        )
