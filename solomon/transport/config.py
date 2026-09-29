"""Solomon 全体の設定 (env / Data Connections) を 1 箇所に集約するリゾルバ。

## 設計方針

Solomon は Cloudera AI Workbench の AMP として配信される。以下の 3 種類の設定源が
混在するが、この 1 モジュールに集約することでコード側は「env の名前」も
「cml.data の呼び方」も意識せずに済むようにする。

1. **AMP Configuration 画面** (Deploy フォーム): ``SOLOMON_LOG_LEVEL``、
   ``NEO4J_MODE`` / ``OPENSEARCH_MODE``、``NEO4J_USERNAME`` / ``NEO4J_PASSWORD``。
2. **Cloudera AI Workbench の Data Connections** (Site Administration →
   Data Connections で設定済み): Trino / S3 の接続情報は Deploy 時に二重入力
   させず、``cml.data_v1`` 経由で取得する。
3. **Post-deploy env** (Project → Settings → Advanced → Environment Variables):
   LLM プロバイダ、Trino 接続名の上書き、CDV base URL などは AMP を Deploy
   した後に Application を再起動する形で反映する。

## 未設定時の挙動

各 ``get_*_config()`` は必須要素が揃わなければ **``None`` を返す**。呼び出し側
(API endpoint / Tool) は ``None`` を検出したら HTTP 503 + guided error を返す
か、Tool レベルで ``error_code=*_NOT_CONFIGURED`` を返す (UI 側で SetupGuide
カードを出すため)。

## import と再読み込みの方針

``cml.data_v1`` は runtime dep として **optional import**。カーネル環境に存在
しなければ env fallback に落ちる。env は **import 時にキャッシュしない** ため、
env 更新後は Application 再起動が必要だが、逆にリクエストごとの再読み込みは
可能 (テストで monkeypatch しやすい副次効果もある)。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

# ----- Data Connections: optional import -----------------------------
# CML カーネル環境では pre-install されているが、local dev では入らない。
# Application 起動直後など import タイミング差を吸収するため lazy に読む。
_cmldata: Any | None = None
_cmldata_import_attempted = False


def _ensure_cmldata() -> Any | None:
    global _cmldata, _cmldata_import_attempted
    if _cmldata_import_attempted:
        return _cmldata
    _cmldata_import_attempted = True
    try:  # pragma: no cover — cml 環境でしか import できない
        import cml.data_v1 as cmldata  # type: ignore

        _cmldata = cmldata
    except ImportError:
        _cmldata = None
    return _cmldata


# ------------------------------------------------------------------ #
# dataclass 定義
# ------------------------------------------------------------------ #
@dataclass(frozen=True)
class TrinoConfig:
    """Trino 接続に必要な設定一式。

    Knox JWT は :class:`~solomon.session.UserContext` から都度取得するため、ここには
    載せない (トークンを config に固めない = ログ / repr に漏れない)。
    """

    host: str
    port: int = 443
    scheme: str = "https"
    verify_ssl: Any = True  # bool | str (CA bundle path)
    catalog: str = "iceberg"
    schema: str = "demo"
    #: Data Connection 由来ならその name。env fallback なら None。
    connection_name: Optional[str] = None


@dataclass(frozen=True)
class S3Config:
    """S3 client 構築用の設定。

    aws credentials は毎回 IDBroker STS 経由で ``UserContext`` から取得するため、
    ここには **絶対に載せない** (Knox JWT と同じ理由: ログに漏らさない)。
    """

    region: str = "us-east-1"
    connection_name: Optional[str] = None
    #: Data Connection が endpoint_url を明示している場合のみ (MinIO 等) 有効
    endpoint_url: Optional[str] = None


@dataclass(frozen=True)
class LLMConfig:
    """LLM プロバイダ選択。

    Post-deploy に Project → Settings → Environment で設定される想定。
    provider ごとに必要な追加 env が異なるので、``build_llm()`` はここから
    LiteLLM の prefix を組み立てる。
    """

    provider: str  # cai | anthropic | openai | bedrock
    model_light: str
    model_strong: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    aws_region: Optional[str] = None  # bedrock only
    #: LiteLLM に渡すそのほかの kwargs (temperature 等) — 将来の拡張用
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CDVConfig:
    """Cloudera Data Visualization の接続情報。

    AMP Deploy 後に Data メニューで CDV を有効化して初めて base URL が確定
    するため、Deploy 時には設定できない。Post-deploy env のみ。
    """

    base_url: str
    trino_connection_id: Optional[str] = None


@dataclass(frozen=True)
class OpenSearchConfig:
    """OpenSearch 接続設定 (external cluster / internal launcher)。

    ``OPENSEARCH_MODE=external`` では Data Hub Semantic Search 等の
    外部クラスタへ接続。``OPENSEARCH_MODE=internal`` では
    opensearch-launcher が起動した co-located クラスタ
    (``.solomon/opensearch_endpoints.json``) へ接続する。
    """

    host: str
    port: int = 9200
    scheme: str = "https"
    verify_ssl: Any = True
    namespace: str = "solomon"
    index_name: str = "solomon-datasets"
    username: Optional[str] = None
    password: Optional[str] = None
    embedding_dim: int = 1024
    connection_name: Optional[str] = None


# ------------------------------------------------------------------ #
# 内部ヘルパ
# ------------------------------------------------------------------ #
def _env(name: str) -> Optional[str]:
    """env を読んで空文字は None として返す。"""
    v = os.environ.get(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


def _normalize_trino_host(host: str, port: int) -> tuple[str, int]:
    """``SOLOMON_TRINO_HOST`` に誤って ``:443`` 等が含まれるケースを正規化する。"""
    text = host.strip()
    if not text or text.startswith("["):
        return text, port
    if ":" in text:
        host_part, _, port_part = text.rpartition(":")
        if port_part.isdigit():
            _logger.warning(
                "trino_config.host_had_embedded_port",
                raw_host=text,
                normalized_host=host_part,
                port=int(port_part),
            )
            return host_part, int(port_part)
    return text, port


def _parse_verify_ssl(raw: Optional[str]) -> Any:
    """``SOLOMON_TRINO_VERIFY_SSL`` の値を bool / path に変換する。"""
    if raw is None:
        return True
    lower = raw.lower()
    if lower in ("false", "0", "no"):
        return False
    if lower in ("true", "1", "yes"):
        return True
    return raw  # ファイルパス (CA bundle)


def _cml_list_connections() -> list[Any]:
    """``cml.data_v1.list_connections`` を optional に呼ぶ。"""
    cmldata = _ensure_cmldata()
    if cmldata is None:
        return []
    try:
        conns = cmldata.list_connections()  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        _logger.debug("cml_data.list_connections_failed", error=str(e))
        return []
    return list(conns or [])


def _cml_get_connection(name: str) -> Optional[Any]:
    """``cml.data_v1.get_connection(name)`` を optional に呼ぶ。"""
    cmldata = _ensure_cmldata()
    if cmldata is None:
        return None
    try:
        return cmldata.get_connection(name)  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        _logger.debug(
            "cml_data.get_connection_failed", name=name, error=str(e)
        )
        return None


def _conn_type(conn: Any) -> str:
    """Data Connection オブジェクトの type 属性を lower-case で返す。"""
    for attr in ("type", "connection_type", "kind"):
        v = getattr(conn, attr, None)
        if isinstance(v, str) and v:
            return v.lower()
    return ""


_S3_CONN_TYPES = frozenset(
    {
        "s3",
        "aws_s3",
        "object_store",
        "object-store",
        "s3_object_store",
        "s3-object-store",
    }
)


def _is_s3_connection(conn: Any) -> bool:
    if _conn_type(conn) in _S3_CONN_TYPES:
        return True
    name = (getattr(conn, "name", None) or "").lower()
    return "object store" in name or name.startswith("s3")


def cml_data_available() -> bool:
    return _ensure_cmldata() is not None


def idbroker_configured() -> bool:
    return _env("SOLOMON_IDBROKER_URL") is not None


def iter_s3_connection_names() -> list[str]:
    """S3 Data Connection 名の試行順 (env → auto-detect → 既定名)。"""
    names: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        text = (raw or "").strip()
        if text and text not in seen:
            seen.add(text)
            names.append(text)

    add(_env("SOLOMON_S3_CONNECTION_NAME"))
    for conn in _cml_list_connections():
        if _is_s3_connection(conn):
            add(getattr(conn, "name", None))
    add("S3 Object Store")
    return names


def _conn_params(conn: Any) -> dict[str, Any]:
    """Data Connection の parameter dict を取り出す。

    ``cml.data_v1`` の実装差 (attribute か dict か) を吸収する。
    """
    for attr in ("parameters", "params", "config", "properties"):
        v = getattr(conn, attr, None)
        if isinstance(v, dict):
            return v
    # namedtuple 的なオブジェクトの場合は _asdict を試す
    to_dict = getattr(conn, "_asdict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:  # noqa: BLE001
            pass
    return {}


# ------------------------------------------------------------------ #
# Trino
# ------------------------------------------------------------------ #
def get_trino_config() -> Optional[TrinoConfig]:
    """Trino 接続設定を解決する。解決順は 4 段:

    1. env ``SOLOMON_TRINO_CONNECTION_NAME`` があれば ``cml.data_v1`` から取得
    2. cml.data の全 connection から Trino/CDW 系を auto-detect (1 件目)
    3. env ``SOLOMON_TRINO_HOST`` 系にフォールバック
    4. 何も無ければ ``None``

    ``SOLOMON_TRINO_CATALOG`` / ``SOLOMON_TRINO_SCHEMA`` は Data Connection の値が
    あればそちらを優先し、env はさらにその上書きとして扱う (デモ運用しやすさ)。
    """
    catalog_env = _env("SOLOMON_TRINO_CATALOG")
    schema_env = _env("SOLOMON_TRINO_SCHEMA")

    # 1) 明示名指定
    name = _env("SOLOMON_TRINO_CONNECTION_NAME")
    conn: Optional[Any] = None
    if name:
        conn = _cml_get_connection(name)
        if conn is None:
            _logger.warning(
                "trino_config.named_connection_missing", name=name
            )

    # 2) auto-detect
    if conn is None:
        for c in _cml_list_connections():
            t = _conn_type(c)
            if t in ("cdw", "trino", "impala", "hive"):
                conn = c
                name = getattr(c, "name", None) or name
                _logger.info(
                    "trino_config.auto_detected",
                    connection_name=name,
                    type=t,
                )
                break

    if conn is not None:
        p = _conn_params(conn)
        host = str(p.get("host") or p.get("hostname") or "").strip()
        if not host:
            _logger.warning(
                "trino_config.connection_missing_host",
                connection_name=name,
            )
        else:
            port_raw = p.get("port") or p.get("http_port") or 443
            try:
                port = int(port_raw)
            except (TypeError, ValueError):
                port = 443
            scheme = str(p.get("http_scheme") or p.get("scheme") or "https")
            verify = _parse_verify_ssl(
                str(p.get("verify_ssl")) if p.get("verify_ssl") is not None else None
            )
            catalog = catalog_env or str(p.get("catalog") or "iceberg")
            schema = schema_env or str(p.get("schema") or p.get("database") or "demo")
            host, port = _normalize_trino_host(host, port)
            return TrinoConfig(
                host=host,
                port=port,
                scheme=scheme,
                verify_ssl=verify,
                catalog=catalog,
                schema=schema,
                connection_name=name,
            )

    # 3) env fallback
    host = _env("SOLOMON_TRINO_HOST")
    if not host:
        _logger.debug("trino_config.not_configured")
        return None
    port = int(_env("SOLOMON_TRINO_PORT") or "443")
    host, port = _normalize_trino_host(host, port)
    scheme = _env("SOLOMON_TRINO_SCHEME") or "https"
    verify = _parse_verify_ssl(_env("SOLOMON_TRINO_VERIFY_SSL"))
    catalog = catalog_env or "iceberg"
    schema = schema_env or "demo"
    return TrinoConfig(
        host=host,
        port=port,
        scheme=scheme,
        verify_ssl=verify,
        catalog=catalog,
        schema=schema,
        connection_name=None,
    )


# ------------------------------------------------------------------ #
# S3
# ------------------------------------------------------------------ #
def get_s3_config() -> Optional[S3Config]:
    """S3 client 用の設定を解決する。

    S3 は認証情報 (AK/SK/session_token) を毎リクエスト IDBroker STS 交換で
    取り直すため、この config は **client 構築時に必要なメタ情報のみ** を持つ。

    解決順:
      1. env ``SOLOMON_S3_CONNECTION_NAME`` があれば ``cml.data_v1`` から取得
      2. cml.data から S3 系 connection を auto-detect
      3. env ``AWS_REGION`` / ``SOLOMON_S3_ENDPOINT_URL`` を単独読み
      4. 全部空でも region の default (``us-east-1``) で ``S3Config`` を返す
         (IDBroker が別途機能する限り取り込みは動くため)
    """
    name = _env("SOLOMON_S3_CONNECTION_NAME")
    conn: Optional[Any] = None
    if name:
        conn = _cml_get_connection(name)

    if conn is None:
        for c in _cml_list_connections():
            if _is_s3_connection(c):
                conn = c
                name = getattr(c, "name", None) or name
                _logger.info(
                    "s3_config.auto_detected", connection_name=name
                )
                break

    if conn is not None:
        p = _conn_params(conn)
        region = str(
            p.get("region") or _env("AWS_REGION") or "us-east-1"
        )
        endpoint = p.get("endpoint_url") or p.get("endpoint") or None
        return S3Config(
            region=region,
            connection_name=name,
            endpoint_url=str(endpoint) if endpoint else None,
        )

    # env only (IDBroker が credentials を出す前提)
    region = _env("AWS_REGION") or "us-east-1"
    endpoint = _env("SOLOMON_S3_ENDPOINT_URL")
    return S3Config(region=region, connection_name=name, endpoint_url=endpoint)


# ------------------------------------------------------------------ #
# LLM
# ------------------------------------------------------------------ #
_DEFAULT_LIGHT_MODEL: dict[str, str] = {
    "cai": "llama-3-8b-instruct",
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "bedrock": "anthropic.claude-haiku-4-5",
}
_DEFAULT_STRONG_MODEL: dict[str, str] = {
    "cai": "llama-3-70b-instruct",
    "anthropic": "claude-sonnet-4-5-20250929",
    "openai": "gpt-4o",
    "bedrock": "anthropic.claude-sonnet-4-20250514-v1:0",
}


def get_llm_config() -> Optional[LLMConfig]:
    """LLM プロバイダ設定を解決する。

    ``SOLOMON_LLM_PROVIDER`` が未設定でも、CAI env
    (``CAI_INFERENCE_BASE_URL`` + ``CAI_INFERENCE_API_KEY``) が両方揃っていれば
    ``provider="cai"`` として動く (後方互換)。

    provider ごとに必要な env が違うので、揃っていなければ ``None`` を返す
    (呼び出し側で 503 に落とす)。
    """
    provider = (_env("SOLOMON_LLM_PROVIDER") or "").lower()
    if not provider:
        # 後方互換: CAI env が両方揃っていれば cai
        if _env("CAI_INFERENCE_BASE_URL") and _env("CAI_INFERENCE_API_KEY"):
            provider = "cai"
        else:
            _logger.debug("llm_config.provider_not_set")
            return None

    if provider not in _DEFAULT_LIGHT_MODEL:
        _logger.warning("llm_config.unknown_provider", provider=provider)
        return None

    model_light = _env("SOLOMON_LLM_ROUTER_MODEL") or _DEFAULT_LIGHT_MODEL[provider]
    model_strong = _env("SOLOMON_LLM_ANALYTICS_MODEL") or _DEFAULT_STRONG_MODEL[provider]

    api_base: Optional[str] = None
    api_key: Optional[str] = None
    aws_region: Optional[str] = None

    if provider == "cai":
        api_base = _env("CAI_INFERENCE_BASE_URL")
        api_key = _env("CAI_INFERENCE_API_KEY")
        if not api_base or not api_key:
            _logger.debug("llm_config.cai_env_missing")
            return None
    elif provider == "anthropic":
        api_key = _env("ANTHROPIC_API_KEY")
        api_base = _env("ANTHROPIC_BASE_URL")  # optional
        if not api_key:
            _logger.debug("llm_config.anthropic_key_missing")
            return None
    elif provider == "openai":
        api_key = _env("OPENAI_API_KEY")
        api_base = _env("OPENAI_BASE_URL")  # optional
        if not api_key:
            _logger.debug("llm_config.openai_key_missing")
            return None
    elif provider == "bedrock":
        aws_region = _env("AWS_REGION")
        if not aws_region:
            _logger.debug("llm_config.bedrock_region_missing")
            return None

    return LLMConfig(
        provider=provider,
        model_light=model_light,
        model_strong=model_strong,
        api_base=api_base,
        api_key=api_key,
        aws_region=aws_region,
    )


# ------------------------------------------------------------------ #
# CDV
# ------------------------------------------------------------------ #
def get_cdv_config() -> Optional[CDVConfig]:
    """Cloudera Data Visualization の設定を解決する。

    CDV は AMP Deploy 後にプロジェクト内で有効化する運用なので、Deploy 時点
    では ``SOLOMON_CDV_BASE_URL`` が空。ここで ``None`` を返せば呼び出し側の
    CDV Tool が ``CDV_NOT_CONFIGURED`` エラーを返し、UI が有効化手順を出す。
    """
    base = _env("SOLOMON_CDV_BASE_URL")
    if not base:
        return None
    return CDVConfig(
        base_url=base.rstrip("/"),
        trino_connection_id=_env("SOLOMON_CDV_TRINO_CONNECTION_ID"),
    )


def get_neo4j_config():
    """Neo4j 接続設定を解決する。NEO4J_URI 未設定なら None。"""
    from solomon.graph.config import get_neo4j_config as _get_neo4j_config

    return _get_neo4j_config()


# ------------------------------------------------------------------ #
# OpenSearch (Cloudera Semantic Search on Data Hub)
# ------------------------------------------------------------------ #
_OPENSEARCH_CONN_TYPES = frozenset(
    {"opensearch", "css", "semantic_search", "elasticsearch"}
)


def _parse_opensearch_endpoint(raw: str) -> tuple[str, int, str]:
    """``https://host:9200`` 形式または ``host`` のみを (host, port, scheme) に分解。"""
    text = raw.strip()
    if "://" in text:
        from urllib.parse import urlparse

        parsed = urlparse(text)
        host = (parsed.hostname or "").strip()
        if not host:
            return "", 9200, "https"
        scheme = parsed.scheme or "https"
        default_port = 443 if scheme == "https" else 9200
        port = parsed.port if parsed.port is not None else default_port
        return host, port, scheme
    return text, 9200, "https"


def _opensearch_config_from_params(
    p: dict[str, Any],
    *,
    connection_name: Optional[str],
    namespace_env: Optional[str],
    index_env: Optional[str],
    embedding_dim_env: Optional[str],
) -> Optional[OpenSearchConfig]:
    endpoint = (
        p.get("endpoint")
        or p.get("endpoint_url")
        or p.get("host")
        or p.get("hostname")
    )
    if not endpoint:
        return None
    host, port, scheme = _parse_opensearch_endpoint(str(endpoint))
    if not host:
        return None
    port_raw = p.get("port") or port
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        pass
    scheme = str(p.get("http_scheme") or p.get("scheme") or scheme)
    verify = _parse_verify_ssl(
        str(p.get("verify_ssl")) if p.get("verify_ssl") is not None else None
    )
    namespace = str(
        namespace_env
        or p.get("namespace")
        or p.get("opensearch_namespace")
        or "solomon"
    )
    index_name = index_env or str(p.get("index") or p.get("index_name") or f"{namespace}-datasets")
    dim_raw = embedding_dim_env or str(p.get("embedding_dim") or "1024")
    try:
        embedding_dim = int(dim_raw)
    except (TypeError, ValueError):
        embedding_dim = 1024
    username = p.get("username") or p.get("user")
    password = p.get("password")
    return OpenSearchConfig(
        host=host,
        port=port,
        scheme=scheme,
        verify_ssl=verify,
        namespace=namespace,
        index_name=index_name,
        username=str(username) if username else None,
        password=str(password) if password else None,
        embedding_dim=embedding_dim,
        connection_name=connection_name,
    )


def _opensearch_config_from_endpoint(
    endpoint: str,
    *,
    namespace_env: Optional[str],
    index_env: Optional[str],
    embedding_dim_env: Optional[str],
    connection_name: Optional[str] = None,
    default_scheme: str = "https",
    default_verify_ssl: Any = True,
) -> Optional[OpenSearchConfig]:
    host, port, scheme = _parse_opensearch_endpoint(endpoint)
    if not host:
        return None
    from solomon.opensearch.env import opensearch_env

    port = int(opensearch_env("PORT") or str(port))
    scheme = opensearch_env("SCHEME") or scheme or default_scheme
    verify_raw = opensearch_env("VERIFY_SSL")
    verify = _parse_verify_ssl(verify_raw) if verify_raw is not None else default_verify_ssl
    namespace = namespace_env or "solomon"
    index_name = index_env or f"{namespace}-datasets"
    dim_raw = embedding_dim_env or "1024"
    try:
        embedding_dim = int(dim_raw)
    except (TypeError, ValueError):
        embedding_dim = 1024
    return OpenSearchConfig(
        host=host,
        port=port,
        scheme=scheme,
        verify_ssl=verify,
        namespace=namespace,
        index_name=index_name,
        username=opensearch_env("USERNAME"),
        password=opensearch_env("PASSWORD"),
        embedding_dim=embedding_dim,
        connection_name=connection_name,
    )


def _get_external_opensearch_config(
    *,
    namespace_env: Optional[str],
    index_env: Optional[str],
    embedding_dim_env: Optional[str],
) -> Optional[OpenSearchConfig]:
    """Production: Data Hub Semantic Search via Data Connection or explicit env."""
    from solomon.opensearch.env import opensearch_env

    name = opensearch_env("CONNECTION_NAME")
    conn: Optional[Any] = None
    if name:
        conn = _cml_get_connection(name)
        if conn is None:
            _logger.warning(
                "opensearch_config.named_connection_missing", name=name
            )

    if conn is None:
        for c in _cml_list_connections():
            if _conn_type(c) in _OPENSEARCH_CONN_TYPES:
                conn = c
                name = getattr(c, "name", None) or name
                _logger.info(
                    "opensearch_config.auto_detected",
                    connection_name=name,
                    type=_conn_type(c),
                )
                break

    if conn is not None:
        cfg = _opensearch_config_from_params(
            _conn_params(conn),
            connection_name=name,
            namespace_env=namespace_env,
            index_env=index_env,
            embedding_dim_env=embedding_dim_env,
        )
        if cfg is not None:
            if namespace_env:
                return replace(cfg, namespace=namespace_env)
            return cfg
        _logger.warning(
            "opensearch_config.connection_missing_endpoint",
            connection_name=name,
        )

    endpoint = opensearch_env("ENDPOINT") or opensearch_env("HOST")
    if not endpoint:
        return None
    return _opensearch_config_from_endpoint(
        endpoint,
        namespace_env=namespace_env,
        index_env=index_env,
        embedding_dim_env=embedding_dim_env,
    )


def _get_internal_opensearch_config(
    *,
    namespace_env: Optional[str],
    index_env: Optional[str],
    embedding_dim_env: Optional[str],
) -> Optional[OpenSearchConfig]:
    """Internal: co-located opensearch-launcher (Neo4j launcher と同型)."""
    from solomon.opensearch.env import opensearch_env

    endpoint = opensearch_env("ENDPOINT") or opensearch_env("HOST")
    if not endpoint:
        from solomon.opensearch.endpoints_file import load_http_hosts

        hosts = load_http_hosts()
        if hosts:
            endpoint = f"http://{hosts[0]}"
    if not endpoint:
        _logger.debug("opensearch_config.internal_launcher_not_ready")
        return None
    return _opensearch_config_from_endpoint(
        endpoint,
        namespace_env=namespace_env,
        index_env=index_env,
        embedding_dim_env=embedding_dim_env,
        default_scheme="http",
        default_verify_ssl=False,
    )


def get_opensearch_config() -> Optional[OpenSearchConfig]:
    """OpenSearch 接続設定。``OPENSEARCH_MODE`` で解決経路を切り替える。

    * ``internal`` (default): opensearch-launcher が書く
      ``.solomon/opensearch_endpoints.json`` / ``OPENSEARCH_ENDPOINT``
    * ``external``: Data Hub Semantic Search — Data Connection または env
    """
    from solomon.opensearch.env import opensearch_env
    from solomon.opensearch.mode import is_internal_opensearch_mode

    namespace_env = opensearch_env("NAMESPACE")
    index_env = opensearch_env("INDEX")
    embedding_dim_env = opensearch_env("EMBEDDING_DIM")

    if is_internal_opensearch_mode():
        return _get_internal_opensearch_config(
            namespace_env=namespace_env,
            index_env=index_env,
            embedding_dim_env=embedding_dim_env,
        )

    cfg = _get_external_opensearch_config(
        namespace_env=namespace_env,
        index_env=index_env,
        embedding_dim_env=embedding_dim_env,
    )
    if cfg is None:
        _logger.debug("opensearch_config.not_configured")
    return cfg


__all__ = [
    "TrinoConfig",
    "S3Config",
    "LLMConfig",
    "CDVConfig",
    "OpenSearchConfig",
    "get_trino_config",
    "get_s3_config",
    "get_llm_config",
    "get_cdv_config",
    "get_neo4j_config",
    "get_opensearch_config",
]
