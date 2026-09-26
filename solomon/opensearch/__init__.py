"""External OpenSearch client (Cloudera Semantic Search on Data Hub).

OpenSearch は Solomon 内で起動しない。Data Hub の Semantic Search for AWS
クラスタへ HTTP で接続する。
"""

from solomon.transport.config import OpenSearchConfig, get_opensearch_config

__all__ = ["OpenSearchConfig", "get_opensearch_config"]
