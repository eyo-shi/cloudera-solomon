"""Solomon 全体の設定 (env / Data Connections) を 1 箇所に集約するリゾルバ。

## 設計方針

Solomon は Cloudera AI Workbench の AMP として配信される。以下の 3 種類の設定源が
混在するが、この 1 モジュールに集約することでコード側は「env の名前」も
「cml.data の呼び方」も意識せずに済むようにする。

1. **AMP Configuration 画面** (Deploy フォーム): ``SOLOMON_LOG_LEVEL``、
   ``TRINO_MODE``、``PUPPYGRAPH_*`` / ``OPENSEARCH_MODE``、
   PuppyGraph Bolt は ``PUPPYGRAPH_URI``（``PUPPYGRAPH_PASSWORD`` は
   ``.solomon/secrets.env`` で上書き可）。
2. **Cloudera AI Workbench の Data Connections** (Site Administration →
   Data Connections で設定済み): S3 等は ``cml.data_v1`` 経由で取得する。
   **Trino (external)** は Application env のみ（``TRINO_URL`` 等）。
3. **Post-deploy env** — 既定はプロジェクト内 ``.solomon/deploy.env`` /
   ``.solomon/secrets.env`` を Application 起動時に読み込む
   (:func:`solomon.infra.deploy_env.bootstrap_deploy_env`)。Project Settings
   の Environment Variables は **非空の値** で上書き可能 (緊急用)。
   変更後は Application 再起動。

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

    ``internal=True`` のとき warehouse-launcher (Trino + DuckDB) へ接続し、
    JWT 認証は使わない。
    """

    host: str
    port: int = 443
    scheme: str = "https"
    verify_ssl: Any = True  # bool | str (CA bundle path)
    catalog: str = "iceberg"
    schema: str = "demo"
    #: 後方互換フィールド（external は env のみのため常に None）。
    connection_name: Optional[str] = None
    #: ``TRINO_MODE=internal`` — co-located Trino + DuckDB (demo warehouse)。
    internal: bool = False
    #: ``jwt`` | ``basic`` | ``auto``（password ありなら basic、なければ jwt）
    auth_mode: str = "auto"
    #: Basic 認証の Trino ユーザー（未設定時は JWT 時と同様に end-user 名）
    service_user: Optional[str] = None
    #: Basic 認証パスワード（env / Connection 由来。JWT モードでは未使用）
    password: Optional[str] = None


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
    """後方互換用の集約 LLM 設定 (単一プロバイダ想定)。

    新規コードは :class:`LLMRoleConfig` と :func:`get_llm_role_config` /
    :func:`get_llm_agent_config` を使う。
    """

    provider: str  # cai | anthropic | openai | bedrock
    model_light: str
    model_strong: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    aws_region: Optional[str] = None  # bedrock only
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMRoleConfig:
    """Role / Agent 単位で解決した LLM (provider + model + 認証)。"""

    role: str
    provider: str
    model: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    aws_region: Optional[str] = None


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
    #: Knox ``.../cdp-proxy-api/opensearch`` 等（``OPENSEARCH_URL`` の path 部）
    url_prefix: str = ""
    #: 業務文書チャンク用インデックス（``OPENSEARCH_DOCS_INDEX`` / Ossie / ``{namespace}-docs``）
    docs_index_name: str = ""
    #: 文書 ``text`` / ``title`` 用アナライザー（``cjk`` | ``kuromoji``）
    docs_analyzer: str = "cjk"


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


_RAG_SOURCE_VALID = frozenset({"table", "graph", "search"})


def get_rag_default_sources() -> frozenset[str]:
    """``SOLOMON_RAG_SOURCES``（カンマ区切り、既定 ``table,graph,search``）。"""
    raw = _env("SOLOMON_RAG_SOURCES") or "table,graph,search"
    out: set[str] = set()
    for part in raw.split(","):
        name = part.strip().lower()
        if not name:
            continue
        if name in _RAG_SOURCE_VALID:
            out.add(name)
        else:
            _logger.warning("rag_config.unknown_source", source=name)
    if not out:
        return frozenset({"table", "graph", "search"})
    return frozenset(out)


def _normalize_trino_host(host: str, port: int) -> tuple[str, int]:
    """``TRINO_HOST`` に誤って ``:443`` 等が含まれるケースを正規化する。"""
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


def _parse_trino_host_port_scheme(
    endpoint: str,
    *,
    default_port: int = 443,
    default_scheme: str = "https",
    port_env: Optional[str] = None,
    scheme_env: Optional[str] = None,
) -> tuple[str, int, str]:
    """``host`` / ``https://host:443`` / ``host:443`` を Trino client 向けに分解する。"""
    text = endpoint.strip()
    if not text:
        return "", default_port, default_scheme
    if "://" in text:
        from urllib.parse import urlparse

        parsed = urlparse(text)
        host = (parsed.hostname or "").strip()
        port = parsed.port if parsed.port is not None else default_port
        scheme = (parsed.scheme or default_scheme).strip().lower()
    else:
        port = default_port
        scheme = default_scheme
        host, port = _normalize_trino_host(text, port)
    if port_env:
        try:
            port = int(port_env)
        except (TypeError, ValueError):
            pass
    if scheme_env:
        scheme = scheme_env.strip().lower()
    return host, port, scheme


def _parse_verify_ssl(raw: Optional[str]) -> Any:
    """``TRINO_VERIFY_SSL`` の値を bool / path に変換する。"""
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
def _get_internal_trino_config(
    *,
    catalog_env: Optional[str],
    schema_env: Optional[str],
) -> Optional[TrinoConfig]:
    """Co-located warehouse-launcher: endpoints file → env override."""
    from solomon.trino.endpoints_file import load_http_hosts
    from solomon.trino.env import trino_env

    host: Optional[str] = None
    port = 8080

    endpoint = trino_env("ENDPOINT") or trino_env("HOST")
    if endpoint:
        from urllib.parse import urlparse

        parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
        if parsed.hostname:
            host = parsed.hostname
            if parsed.port is not None:
                port = parsed.port

    if not host:
        hosts = load_http_hosts()
        if hosts:
            first = hosts[0]
            if ":" in first:
                host_part, _, port_part = first.rpartition(":")
                host = host_part
                if port_part.isdigit():
                    port = int(port_part)
            else:
                host = first

    if not host:
        _logger.debug("trino_config.internal_launcher_not_ready")
        return None

    scheme = trino_env("SCHEME") or "http"
    verify = _parse_verify_ssl(trino_env("VERIFY_SSL"))
    if verify is True and scheme == "http":
        verify = False
    catalog = catalog_env or "iceberg"
    schema = schema_env or "demo"
    host, port = _normalize_trino_host(host, port)
    return TrinoConfig(
        host=host,
        port=port,
        scheme=scheme,
        verify_ssl=verify,
        catalog=catalog,
        schema=schema,
        connection_name=None,
        internal=True,
    )


def _trino_auth_from_env() -> tuple[str, Optional[str], Optional[str]]:
    from solomon.trino.env import trino_env

    auth_raw = (trino_env("AUTH") or "auto").strip().lower()
    if auth_raw not in ("jwt", "basic", "auto"):
        auth_raw = "auto"
    service_user = trino_env("USER")
    if service_user is not None:
        service_user = service_user.strip() or None
    password = trino_env("PASSWORD")
    if password is not None:
        password = password.strip() or None
    return auth_raw, service_user, password


def _get_external_trino_config(
    *,
    catalog_env: Optional[str],
    schema_env: Optional[str],
) -> Optional[TrinoConfig]:
    """Production CDW / Trino — Application env のみ（``TRINO_URL`` / ``TRINO_HOST`` 等）。"""
    from solomon.trino.env import trino_endpoint_url, trino_env

    endpoint = trino_endpoint_url()
    if not endpoint:
        _logger.debug("trino_config.not_configured")
        return None
    host, port, scheme = _parse_trino_host_port_scheme(
        endpoint,
        default_port=int(trino_env("PORT") or "443"),
        default_scheme=trino_env("SCHEME") or "https",
        port_env=trino_env("PORT"),
        scheme_env=trino_env("SCHEME"),
    )
    if not host:
        _logger.debug("trino_config.invalid_host")
        return None
    verify = _parse_verify_ssl(trino_env("VERIFY_SSL"))
    catalog = catalog_env or "iceberg"
    schema = schema_env or "demo"
    auth_mode, service_user, password = _trino_auth_from_env()
    return TrinoConfig(
        host=host,
        port=port,
        scheme=scheme,
        verify_ssl=verify,
        catalog=catalog,
        schema=schema,
        connection_name=None,
        internal=False,
        auth_mode=auth_mode,
        service_user=service_user,
        password=password,
    )


def get_trino_config() -> Optional[TrinoConfig]:
    """Trino 接続設定を解決する。

    * ``TRINO_MODE=internal``: warehouse-launcher の Trino + DuckDB
    * ``TRINO_MODE=external``: CDW / Trino — Application env (``TRINO_URL`` 等)
    """
    from solomon.trino.mode import is_internal_trino_mode

    from solomon.trino.env import trino_env

    catalog_env = trino_env("CATALOG")
    schema_env = trino_env("SCHEMA")

    if is_internal_trino_mode():
        return _get_internal_trino_config(
            catalog_env=catalog_env,
            schema_env=schema_env,
        )

    return _get_external_trino_config(
        catalog_env=catalog_env,
        schema_env=schema_env,
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

_DEFAULT_EMBEDDING_MODEL: dict[str, str] = {
    "cai": "bge-m3",
    "anthropic": "bge-m3",
    "openai": "text-embedding-3-small",
    "bedrock": "amazon.titan-embed-text-v2:0",
}

_LLM_ROLE_NAMES = frozenset({"light", "strong", "embedding"})

# Agent key -> 既定 role (Agent 専用 env 未設定時)
AGENT_LLM_DEFAULT_ROLE: dict[str, str] = {
    "intent_classifier": "light",
    "dispatcher": "light",
    "table_inspector": "light",
    "viz_planner": "light",
    "summary_writer": "strong",
    "dashboard_builder": "strong",
    "rag_synthesis": "strong",
    "rag_agent": "strong",
    "excel_validate": "light",
    "doc_query_expansion": "light",
    "text2sql": "strong",
}


def _cai_workload_token() -> Optional[str]:
    """Workbench の ``/tmp/jwt`` (``SOLOMON_CML_JWT_PATH``) の access_token。

    CAI Inference の認証は短命な CDP workload JWT。固定の API キーを env に
    書くと期限切れになるため、キー未設定時は呼び出しごとにファイルを読む。
    """
    from solomon.transport.auth import load_workload_jwt_token

    return load_workload_jwt_token()


def _resolve_default_llm_provider() -> Optional[str]:
    provider = (_env("SOLOMON_LLM_PROVIDER") or "").lower()
    if provider:
        if provider not in _DEFAULT_LIGHT_MODEL:
            _logger.warning("llm_config.unknown_provider", provider=provider)
            return None
        return provider
    if _env("CAI_INFERENCE_BASE_URL") and (
        _env("CAI_INFERENCE_API_KEY") or _cai_workload_token()
    ):
        return "cai"
    _logger.debug("llm_config.provider_not_set")
    return None


def _provider_for_role(role: str) -> Optional[str]:
    role_keys: tuple[str, ...]
    if role == "light":
        role_keys = ("SOLOMON_LLM_LIGHT_PROVIDER", "SOLOMON_LLM_ROUTER_PROVIDER")
    elif role == "strong":
        role_keys = ("SOLOMON_LLM_STRONG_PROVIDER", "SOLOMON_LLM_ANALYTICS_PROVIDER")
    elif role == "embedding":
        role_keys = ("SOLOMON_LLM_EMBEDDING_PROVIDER",)
    else:
        return None
    for key in role_keys:
        raw = (_env(key) or "").lower()
        if raw:
            if raw not in _DEFAULT_LIGHT_MODEL:
                _logger.warning("llm_config.unknown_provider", provider=raw, role=role)
                return None
            return raw
    return _resolve_default_llm_provider()


# Role 別エンドポイント上書き (別名は provider / model と同じ ROUTER / ANALYTICS)。
# Cloudera AI Inference はエンドポイントごとに URL が分かれるため、light / strong /
# embedding を別モデルにするにはここで URL を分ける。
_ROLE_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "light": ("LIGHT", "ROUTER"),
    "strong": ("STRONG", "ANALYTICS"),
    "embedding": ("EMBEDDING",),
}


def _role_endpoint_overrides(role: str) -> tuple[Optional[str], Optional[str]]:
    """``SOLOMON_LLM_<ROLE>_BASE_URL`` / ``_API_KEY`` を返す (未設定は None)。"""
    names = _ROLE_ENV_NAMES.get(role, ())
    base_url = next(
        (v for n in names if (v := _env(f"SOLOMON_LLM_{n}_BASE_URL"))), None
    )
    api_key = next(
        (v for n in names if (v := _env(f"SOLOMON_LLM_{n}_API_KEY"))), None
    )
    return base_url, api_key


def _model_for_role(role: str, provider: str) -> str:
    if role == "light":
        return (
            _env("SOLOMON_LLM_ROUTER_MODEL")
            or _env("SOLOMON_LLM_LIGHT_MODEL")
            or _DEFAULT_LIGHT_MODEL[provider]
        )
    if role == "strong":
        return (
            _env("SOLOMON_LLM_ANALYTICS_MODEL")
            or _env("SOLOMON_LLM_STRONG_MODEL")
            or _DEFAULT_STRONG_MODEL[provider]
        )
    if role == "embedding":
        return (
            _env("SOLOMON_LLM_EMBEDDING_MODEL")
            or _DEFAULT_EMBEDDING_MODEL.get(provider, "bge-m3")
        )
    return _DEFAULT_LIGHT_MODEL[provider]


_EMBEDDING_PURPOSES = frozenset({"query", "passage"})


def embedding_model_for_purpose(base_model: str, purpose: str) -> str:
    """検索 (query) / 索引 (passage) 別の embedding model ID を返す。

    非対称 embedding モデル (NVIDIA embedqa 等) は用途で model ID を変える。
    CAI Inference では ``nvidia/llama-3.2-nv-embedqa-1b-v2-query`` /
    ``...-passage`` のように末尾で切り替える。
    ``SOLOMON_LLM_EMBEDDING_QUERY_MODEL`` / ``_PASSAGE_MODEL`` が未設定なら
    ``base_model`` (``SOLOMON_LLM_EMBEDDING_MODEL``) をそのまま使う。
    """
    if purpose not in _EMBEDDING_PURPOSES:
        raise ValueError(f"unknown embedding purpose: {purpose!r}")
    return _env(f"SOLOMON_LLM_EMBEDDING_{purpose.upper()}_MODEL") or base_model


def get_embedding_dimensions() -> Optional[int]:
    """``SOLOMON_LLM_EMBEDDING_DIMENSIONS`` (Matryoshka 対応モデルの出力次元)。

    未設定ならモデル既定の次元。OpenSearch の ``OPENSEARCH_EMBEDDING_DIM`` と
    一致させる必要がある。
    """
    raw = _env("SOLOMON_LLM_EMBEDDING_DIMENSIONS")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        _logger.warning("llm_config.invalid_embedding_dimensions", value=raw)
        return None
    if value <= 0:
        _logger.warning("llm_config.invalid_embedding_dimensions", value=raw)
        return None
    return value


def _credentials_for_provider(
    provider: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], Optional[str]] | None:
    """Return (api_base, api_key, aws_region) or None if required env missing.

    ``base_url`` / ``api_key`` は role / Agent 別の上書き。未指定なら provider 共通の
    env (``CAI_INFERENCE_*`` 等) を使う。bedrock では使わない。
    cai でキーがどこにも無ければ Workbench の ``/tmp/jwt`` を使う。
    """
    api_base: Optional[str] = None
    aws_region: Optional[str] = None

    if provider == "cai":
        api_base = base_url or _env("CAI_INFERENCE_BASE_URL")
        api_key = api_key or _env("CAI_INFERENCE_API_KEY") or _cai_workload_token()
        if not api_base or not api_key:
            _logger.debug("llm_config.cai_env_missing")
            return None
    elif provider == "anthropic":
        api_key = api_key or _env("ANTHROPIC_API_KEY")
        api_base = base_url or _env("ANTHROPIC_BASE_URL")
        if not api_key:
            _logger.debug("llm_config.anthropic_key_missing")
            return None
    elif provider == "openai":
        api_key = api_key or _env("OPENAI_API_KEY")
        api_base = base_url or _env("OPENAI_BASE_URL")
        if not api_key:
            _logger.debug("llm_config.openai_key_missing")
            return None
    elif provider == "bedrock":
        if base_url or api_key:
            _logger.warning("llm_config.bedrock_ignores_endpoint_override")
        api_key = None
        aws_region = _env("AWS_REGION") or _env("SOLOMON_AWS_REGION")
        if not aws_region:
            _logger.debug("llm_config.bedrock_region_missing")
            return None
    else:
        return None

    return api_base, api_key, aws_region


def get_llm_role_config(role: str) -> Optional[LLMRoleConfig]:
    """Role ごとの provider + model + 認証を解決する。"""
    if role not in _LLM_ROLE_NAMES:
        return None
    provider = _provider_for_role(role)
    if provider is None:
        return None
    role_base_url, role_api_key = _role_endpoint_overrides(role)
    creds = _credentials_for_provider(
        provider, base_url=role_base_url, api_key=role_api_key
    )
    if creds is None:
        return None
    api_base, api_key, aws_region = creds
    return LLMRoleConfig(
        role=role,
        provider=provider,
        model=_model_for_role(role, provider),
        api_base=api_base,
        api_key=api_key,
        aws_region=aws_region,
    )


def get_llm_agent_config(agent_key: str) -> Optional[LLMRoleConfig]:
    """Crew Agent 単位の LLM 設定 (Agent env があれば role より優先)。"""
    key = (agent_key or "").strip().lower()
    if not key:
        return None

    env_prefix = f"SOLOMON_LLM_AGENT_{key.upper()}_"
    provider_override = (_env(f"{env_prefix}PROVIDER") or "").lower()
    model_override = _env(f"{env_prefix}MODEL")
    base_url_override = _env(f"{env_prefix}BASE_URL")
    api_key_override = _env(f"{env_prefix}API_KEY")

    default_role = AGENT_LLM_DEFAULT_ROLE.get(key, "light")
    base = get_llm_role_config(default_role)
    if base is None and not provider_override:
        return None

    provider = provider_override or (base.provider if base else None)
    if not provider or provider not in _DEFAULT_LIGHT_MODEL:
        if provider_override:
            _logger.warning("llm_config.unknown_provider", provider=provider, agent=key)
        return None

    # 既定 role と同じ provider なら role 別エンドポイント上書きも引き継ぐ
    role_base_url: Optional[str] = None
    role_api_key: Optional[str] = None
    if base is not None and provider == base.provider:
        role_base_url, role_api_key = _role_endpoint_overrides(default_role)

    creds = _credentials_for_provider(
        provider,
        base_url=base_url_override or role_base_url,
        api_key=api_key_override or role_api_key,
    )
    if creds is None:
        return None
    api_base, api_key, aws_region = creds

    if model_override:
        model = model_override
    elif base is not None and provider == base.provider:
        model = base.model
    else:
        model = _model_for_role(default_role, provider)

    return LLMRoleConfig(
        role=f"agent:{key}",
        provider=provider,
        model=model,
        api_base=api_base,
        api_key=api_key,
        aws_region=aws_region,
    )


def get_llm_config() -> Optional[LLMConfig]:
    """後方互換: light role を基準に集約 ``LLMConfig`` を返す。"""
    light = get_llm_role_config("light")
    if light is None:
        return None
    strong = get_llm_role_config("strong")
    if strong is None:
        return None
    return LLMConfig(
        provider=light.provider,
        model_light=light.model,
        model_strong=strong.model,
        api_base=light.api_base,
        api_key=light.api_key,
        aws_region=light.aws_region or strong.aws_region,
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


def get_graph_config():
    """PuppyGraph Bolt 接続設定。PUPPYGRAPH_URI 未設定なら None。"""
    from solomon.graph.config import get_graph_config as _get_graph_config

    return _get_graph_config()


# ------------------------------------------------------------------ #
# OpenSearch (Cloudera Semantic Search on Data Hub)
# ------------------------------------------------------------------ #
_OPENSEARCH_CONN_TYPES = frozenset(
    {"opensearch", "css", "semantic_search", "elasticsearch"}
)


def _parse_opensearch_endpoint(raw: str) -> tuple[str, int, str, str]:
    """``https://host/path`` を (host, port, scheme, url_prefix) に分解。"""
    text = raw.strip()
    if "://" in text:
        from urllib.parse import urlparse

        parsed = urlparse(text)
        host = (parsed.hostname or "").strip()
        if not host:
            return "", 9200, "https", ""
        scheme = parsed.scheme or "https"
        default_port = 443 if scheme == "https" else 9200
        port = parsed.port if parsed.port is not None else default_port
        prefix = (parsed.path or "").strip()
        if prefix.endswith("/"):
            prefix = prefix.rstrip("/")
        return host, port, scheme, prefix
    return text, 9200, "https", ""


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
    host, port, scheme, url_prefix = _parse_opensearch_endpoint(str(endpoint))
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
        url_prefix=url_prefix,
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
    host, port, scheme, url_prefix = _parse_opensearch_endpoint(endpoint)
    if not host:
        return None
    from solomon.opensearch.env import opensearch_env, opensearch_username

    prefix_env = opensearch_env("URL_PREFIX") or opensearch_env("PATH_PREFIX")
    if prefix_env is not None:
        url_prefix = prefix_env.strip().rstrip("/")
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
        username=opensearch_username(),
        password=opensearch_env("PASSWORD"),
        embedding_dim=embedding_dim,
        connection_name=connection_name,
        url_prefix=url_prefix,
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

    from solomon.opensearch.env import opensearch_endpoint_url

    endpoint = opensearch_endpoint_url()
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
    """Internal: co-located opensearch-launcher."""
    from solomon.opensearch.env import opensearch_env

    from solomon.opensearch.env import opensearch_endpoint_url

    endpoint = opensearch_endpoint_url()
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

    * ``internal``: opensearch-launcher が書く
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
        return None
    return _enrich_opensearch_config(cfg)


def _enrich_opensearch_config(cfg: OpenSearchConfig) -> OpenSearchConfig:
    from solomon.opensearch.doc_index import resolve_docs_analyzer, resolve_docs_index_name

    return replace(
        cfg,
        docs_index_name=resolve_docs_index_name(cfg),
        docs_analyzer=resolve_docs_analyzer(),
    )


__all__ = [
    "TrinoConfig",
    "S3Config",
    "LLMConfig",
    "CDVConfig",
    "OpenSearchConfig",
    "get_trino_config",
    "get_s3_config",
    "LLMRoleConfig",
    "AGENT_LLM_DEFAULT_ROLE",
    "get_llm_config",
    "get_llm_role_config",
    "get_llm_agent_config",
    "embedding_model_for_purpose",
    "get_embedding_dimensions",
    "get_cdv_config",
    "get_graph_config",
    "get_opensearch_config",
    "get_rag_default_sources",
]
