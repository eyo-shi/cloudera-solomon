# Solomon

Cloudera AI Agent Studio 上で動作する自然言語データ分析マルチエージェント。ユーザーが日本語 / 英語で問い合わせるだけで **投入済み** Lakehouse / グラフ / Semantic Search を横断し、**テーブルサマリー生成 / Cloudera Data Visualization ダッシュボード作成 / ナレッジ横断検索 (Agentic RAG)** を実行する。3 ペイン Web UI (React + Vite) + FastAPI バックエンドを Cloudera AI Workbench Application として配信する。

**S3 → Iceberg / OpenSearch へのデータ取り込み**および **PuppyGraph 上の graph schema 定義**は別プロジェクトの責務とし、本リポジトリには含めない。

セマンティックレイヤは **Apache Ossie**（YAML 仕様）を採用し、`semantic/` 配下で Git 管理する。

## 構成

```
solomon/           Python パッケージ (Crew + FastAPI)
  router/       Router Crew (intent 分類 / ディスパッチ)
  graph/        PuppyGraph (Bolt/openCypher) ・Schema ブラウズ API (読み取り)
  opensearch/   外部 OpenSearch (Cloudera Semantic Search) クライアント
  rag/          Agentic RAG (分類 / オーケストレーション / 合成)
  analytics/    Analytics Crew (サマリー / ダッシュボード)
  semantic/     Ossie 本家形式の読込・検索・集約コンテキスト
  session/      セッション、リクエスト、メモリ
  transport/    Knox JWT / HTTP / ロギング共通層
  tools/        CrewAI Tool 実装 (S3 / Trino / Graph Cypher / OpenSearch / Text2SQL 等)
  api/          FastAPI (SSE ストリーム、静的 SPA 配信)
  demo/         デモ用ウォームアップ

solomon_ui/        React + TypeScript + Vite (3 ペイン UI)
  src/panes/
    TreePane/   左: Knowledge Source Explorer (Tables / Storage / Graph / Search)
    ResultPane/ 中央: Table / Dashboard / Summary / SQL / File / Graph のタブ
    ChatPane/   右: SSE ストリーム対応チャット

semantic/models/  Apache Ossie セマンティックモデル (1 ファイル = 1 モデル)
tests/          pytest
agent_studio_manifest/     Agent Studio 用 tools/agents/crews YAML (自動生成)
.project-metadata.yaml     Cloudera AI Workbench (AMP) マニフェスト
application.json           Workbench Application 起動定義
pyproject.toml
```

## Knowledge Source

Solomon は 4 つの Knowledge Source を UI と Agent から共通利用する。

| Source | UI タブ | バックエンド | 用途 |
|---|---|---|---|
| **Lakehouse** | Tables | Trino / Iceberg (`/api/catalog/*`) | テーブル・カラム探索、SQL 分析 |
| **Storage** | Storage | S3 (`/api/files/*`) | 生ファイル探索・プレビュー |
| **Graph** | Graph | PuppyGraph (`/api/graph/*`) | リネージ・関係 traversals (openCypher) |
| **Semantic Search** | Search | OpenSearch (`/api/search/*`) | ベクトル + キーワード検索インデックス |

左ペイン (TreePane) でタブを切り替え、Tables ではテーブル選択 → 中央ペインに Table Preview、Graph では Node Label / Relationship Type / Property Key をクリック → 中央ペインに **Cytoscape** グラフ可視化、Search ではインデックス済みドキュメント一覧を表示する。

## Agentic RAG

自然言語のナレッジ質問は Router が `KNOWLEDGE_RAG` intent に振り分ける。

**既定 (`SOLOMON_RAG_ENGINE=agent`)** — ReAct 型 **Knowledge Agent**（最大 8 手）が `sql_query` / `graph_query` / `doc_search` を litellm 経由で自律的に組み合わせ、SQL・グラフ・文書を横断して回答する。グラフの意味論は `SOLOMON_GRAPH_SCHEMA_FILE`（既定 `semantic/graph/schema.yaml`）をシステムプロンプトに載せる。LLM は `rag_agent`（strong ロール、`SOLOMON_LLM_AGENT_RAG_AGENT_*` で上書き可）。ツール呼び出し形式は `SOLOMON_RAG_TOOL_MODE=auto|native|json`。

**heuristic (`SOLOMON_RAG_ENGINE=heuristic`)** — 従来どおり正規表現で 1 戦略を選び固定パイプラインを 1 回実行する。

**ソース構成** — `table` / `graph` / `search` をリクエストごとに ON/OFF（`POST /api/wish` の `sources`、省略時は `SOLOMON_RAG_SOURCES`）。Chat の 4 択（テーブルのみ / ＋Graph / ＋Search / 全部）で切り替え、再起動不要。

| 戦略 (heuristic) | 主なソース |
|---|---|
| `GRAPH_QUERY` | PuppyGraph (Lakehouse/RDB 上の graph schema) |
| `SQL_ANALYTICS` | Ossie + OpenSearch コンテキスト → Trino Text2SQL |
| `KEYWORD` / `HYBRID` | OpenSearch (BM25 / k-NN / RRF) |
| `COMPOSITE` | 上記の組み合わせ |

heuristic で graph ヒットがある場合は中央ペインに Graph 可視化タブを自動で開く（agent モードでは未対応）。

## PuppyGraph

Graph タブは PuppyGraph の Bolt (7687) に接続し、`CALL db.labels()` 等でスキーマを取得する。Label / Relationship / Property Key クリックで openCypher を API 側が生成・実行する。Iceberg / PostgreSQL 等の catalog と graph schema は **PuppyGraph 側**で管理する。

## 実装ステータス

MVP + Knowledge Source 拡張が `main` に入っている:

| モジュール | 内容 |
|---|---|
| `solomon.transport` | Knox JWT / user_context / HTTP client / structlog / `BaseSolomonTool` |
| `solomon.tools` | S3 / Trino / フォーマット判定 / Excel ヘッダー検出 / CDV / Graph Cypher / OpenSearch / Text2SQL |
| `solomon.graph` | PuppyGraph Bolt 接続、Schema ブラウズ (`browse.py`) |
| `solomon.opensearch` | 外部 OpenSearch 接続 (Data Hub Semantic Search)、keyword / vector / hybrid 検索 |
| `solomon.rag` | Agentic RAG (classifier / orchestrator / synthesizer) |
| `solomon.analytics.AnalyticsCrew` | Summary パス (2 タスク) + Dashboard パス (4 タスク、VizPlanner + CDV) |
| `solomon.router.RouterCrew` | intent 分類 + Python レベルディスパッチ (`KNOWLEDGE_RAG` 含む) |
| `solomon.api` | FastAPI (`/api/wish` SSE / `/api/catalog` / `/api/graph` / `/api/search` / `/api/files` / `/api/query` / SPA mount) |
| `solomon_ui` | React + Vite 3 ペイン UI (4 Knowledge Source タブ + Graph 可視化 + ChatPane SSE) |
| `solomon.manifest` | Python 定義から Agent Studio manifest を自動生成 |
| `.project-metadata.yaml` | Cloudera AI Workbench (AMP) 登録用マニフェスト |

未着手 (v2 候補): TablePreview の仮想スクロール、Graph 2-hop/3-hop UI、Ossie バッジの実 YAML 判定、セッション履歴の hydrate、Analytics の Hierarchical Process 移行。

## 開発

CDW + Iceberg / PuppyGraph / OpenSearch の**デモ環境構築・リハーサル**は [demo/SETUP.md](demo/SETUP.md) を参照（`demo.loader` / `demo.validate` / `demo.checks.preflight`）。

### バックエンド

Python **3.12** 以上が必要です。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest             # スモークテスト
uvicorn solomon.api.main:app --reload   # http://127.0.0.1:8000
```

### フロントエンド

```bash
cd solomon_ui
npm ci             # package-lock.json 必須 (リポジトリ同梱)
npm run dev        # http://localhost:5173  (API は /api を 127.0.0.1:8000 にプロキシ)
npm run build      # solomon/api/static/ に SPA を出力
```

Graph 可視化には **cytoscape** を使用する (`npm ci` で自動インストール)。

### Cloudera AI Workbench で配信

AMP Deploy では Step 2 が nvm + `npm ci && npm run build` を自動実行する。
手動ビルドする場合のみ:

1. `cd solomon_ui && npm ci && npm run build`
2. Workbench Application として `python -m solomon.api.main` を起動 (`CDSW_APP_PORT` を uvicorn に渡す)
3. FastAPI が `/api/*` と `/` (SPA) を配信

## Deploy フォーム (AMP Configuration 画面)

Deploy 時に Configuration 画面へ表示される Environment Variables (すべて optional):

| 変数 | デフォルト | 説明 |
|---|---|---|
| `SOLOMON_LOG_LEVEL` | `INFO` | ログレベル |
| `TRINO_MODE` | `external` | Trino / Tables: CDW Trino / `internal` = warehouse-launcher |
| `PUPPYGRAPH_MODE` | `internal` | PuppyGraph: endpoints file / `external` = 外部 Bolt |
| `OPENSEARCH_MODE` | `external` | OpenSearch: Semantic Search / `internal` = launcher |

PuppyGraph の ``PUPPYGRAPH_URI`` は **Deploy フォームに出さない**（post-deploy の ``.solomon/deploy.env``）。

launcher のメモリ・PVC 等のチューニングは Deploy フォームには出さない。
必要な場合のみ Deploy 後に **Project → Settings → Advanced → Environment Variables**
で設定する (`.env.example` の optional セクション参照)。

Air-gap で AMP Deploy する場合（Runtime / UI / launcher イメージの mirror）は
[docs/airgap_amp.md](docs/airgap_amp.md) を参照。

## Deploy 後の設定手順 (Post-Deploy Configuration)

Post-deploy 設定の **正本** はプロジェクト永続領域の **``.solomon/deploy.env``**
（dotenv 形式）。AMP Deploy 時に ``amp/06_ensure_deploy_env.py`` が、無ければ
``deploy/deploy.env.example`` から生成する。秘匿だけ **``.solomon/secrets.env``**
（Git 除外）に分けてもよい。

Application 起動時（``amp/05_start_application.py`` / ``python -m solomon.api.main``）に
ファイルが ``os.environ`` へマージされる。**Solomon Application を Restart** すると反映される。

| 優先度 | 設定源 |
|--------|--------|
| 高 | Project → Settings → Environment Variables（**非空**の値のみ上書き・緊急用） |
| 中 | ``.solomon/secrets.env`` → ``.solomon/deploy.env``（後者を先に読み、secrets が上書き） |
| 低 | AMP Configuration 画面の default |

ファイルを常に優先したい場合は ``SOLOMON_DEPLOY_ENV_OVERRIDE=true`` を deploy.env に書く
（``CDSW_*`` 等のプラットフォーム注入キーは除外）。

**external** モードでは Trino / OpenSearch / PuppyGraph / LLM / CDV を上記ファイルに記載する。
Trino / S3 の Data Connections は従来どおり **Site Administration** が SSOT の場合あり
（README 各セクション参照）。ローカル開発は引き続き ``.env``（``.env.example`` 参照）でも可。

未設定のまま UI で該当機能を叩くと、API は HTTP 503 + JSON (`{error_code, message,
instruction}`) を返し、UI の **SetupGuide カード** が手順を表示する。

### 1. Trino / Tables への接続

Deploy 時に `TRINO_MODE` で接続方式を切り替える (デフォルト `external`)。

| モード | 用途 | 設定 |
|---|---|---|
| `internal` (デフォルト) | CML 内部デモ | `warehouse-launcher` が Trino + DuckDB (catalog `iceberg`) を 1 Pod で起動 |
| `external` | 本番 CDW | Data Connection または `TRINO_HOST` 等 (下記) |

**internal (`TRINO_MODE=internal`)**

- AMP Deploy で `warehouse-launcher` が起動
- `demo` スキーマに `customers` / `orders` を seed (Tables タブですぐ確認可能)
- ファイル取り込みはカタログ名 `iceberg` のまま、実体は DuckDB 向けの通常 `CREATE TABLE` + `INSERT`（Iceberg の `WITH (format=…)` は使わない）
- Solomon は `.solomon/trino_endpoints.json` から HTTP 接続先を自動解決
- DNS が通らない場合のみ `TRINO_ENDPOINT` を post-deploy で設定

**external (`TRINO_MODE=external`)**

Post-deploy（Project → Settings → Environment Variables）に **Application env のみ** 設定:

- **接続先**（いずれか）: `TRINO_URL`（推奨・1 行）または `TRINO_HOST` + `TRINO_PORT` (443) + `TRINO_SCHEME` (https)
- `TRINO_VERIFY_SSL` (default `true`)
- `TRINO_CATALOG` (default `iceberg`)
- `TRINO_SCHEMA` (default `demo`)
- 製造デモ: `SOLOMON_SILVER_SCHEMA=inspection_silver`
- **認証**: 既定は UI ログインユーザーの **Knox JWT**。Basic の場合は
  `TRINO_USER` + `TRINO_PASSWORD`（`TRINO_AUTH=auto` なら password ありで Basic）

旧名 `SOLOMON_TRINO_*` も後方互換で読み取る。

### 2. S3 への接続

詳細: [docs/s3_connectivity.md](docs/s3_connectivity.md)

- **推奨 (CDP on AWS)**: `SOLOMON_IDBROKER_URL` + ログインユーザーの Knox JWT → STS。
  **S3 が Data Connections に無くても動く**（新環境で S3 タイプが出ない場合はこちら）。
- **Storage タブ**: `SOLOMON_S3_BUCKETS` に実バケット名（カンマ区切り）。未設定は `demo-bucket`。
- **IDBroker 未設定時のみ**: S3 Data Connection（`SOLOMON_S3_CONNECTION_NAME` または自動検出）。
- `SOLOMON_AWS_REGION` (default `us-east-1`)。AMP に AWS access key は置かない。

トラブルシュート: ログイン後 `GET /api/files/diagnostics`。

### 3. PuppyGraph (Graph / openCypher)

Graph タブ・``graph_cypher_query`` Tool は **PuppyGraph Bolt (7687)** に接続する。

Deploy 時に ``PUPPYGRAPH_MODE`` を選ぶ (デフォルト ``internal``)。

| モード | 用途 | 設定 |
|---|---|---|
| `internal` (デフォルト) | CML 内部 | `puppygraph-launcher` が K8s 上で PuppyGraph を起動し、``.solomon/puppygraph_endpoints.json`` を Solomon と共有 |
| `external` | 外部 PuppyGraph | ``.solomon/deploy.env`` に ``PUPPYGRAPH_URI=bolt://host:7687`` |

**internal (`PUPPYGRAPH_MODE=internal`)**

- AMP Deploy で `puppygraph-launcher` が起動（K8s 上で **PuppyGraph コンテナイメージ**を pull — 既定 `puppygraph/puppygraph:1.15.0`、OpenSearch / Trino と同型）
- Bolt ready 後に ``.solomon/puppygraph_endpoints.json`` を自動更新
- **Solomon Application を Restart** して Graph タブ / RAG graph 検索を有効化
- DNS が通らない場合のみ ``PUPPYGRAPH_URI=bolt://<ClusterIP>:7687`` を post-deploy で設定
- Iceberg / Trino catalog と graph schema は **PuppyGraph Web UI**（Pod 8081 / in-cluster）で定義 — Solomon はアップロードしない
- 認証: ``PUPPYGRAPH_USERNAME`` / ``PUPPYGRAPH_PASSWORD``（``secrets.env`` 可。launcher Pod と Solomon で一致させる）
- ``GET /api/graph/meta`` で接続可否を確認

未設定時は Graph タブ・Agentic RAG の graph 検索が ``GRAPH_NOT_CONFIGURED`` で停止する。

### 4. OpenSearch / Semantic Search への接続

Deploy 時に `OPENSEARCH_MODE` で接続方式を切り替える (デフォルト `external`)。
Solomon プロセス内では OpenSearch サーバーは起動しない。

| モード | 用途 | 設定 |
|---|---|---|
| `internal` (デフォルト) | CML 内部 | `opensearch-launcher` が K8s 上で OpenSearch を起動し、`.solomon/opensearch_endpoints.json` を Solomon と共有 |
| `external` | 外部クラスタ | Data Hub **Semantic Search for AWS** 等 — Data Connection または env で接続 |

**internal (`OPENSEARCH_MODE=internal`)**

- AMP Deploy で `opensearch-launcher` が起動
- OpenSearch 起動後に `solomon-datasets` インデックスを自動作成 (Solomon 起動時も再試行)
- **OpenSearch Dashboards** を同 Pod で起動し、Launcher Application URL の `/dashboards/` から利用
- Application Log に HTTP エンドポイントが出力される
- DNS が通らない場合は `OPENSEARCH_ENDPOINT` を post-deploy で設定

**external (`OPENSEARCH_MODE=external`)**

- launcher は no-op
- Data Connections に OpenSearch connection を登録済みなら
  `OPENSEARCH_CONNECTION_NAME` を設定 (省略時は OpenSearch タイプを自動検出)
- 直接指定: `OPENSEARCH_ENDPOINT`, `OPENSEARCH_NAMESPACE`, 認証情報など

Ingestion 完了後に Ossie dataset が OpenSearch にインデックスされる。
未設定時は Search タブ・RAG の keyword/hybrid 検索が `OPENSEARCH_NOT_CONFIGURED` で停止する。

### 5. LLM プロバイダ

**既定:** `SOLOMON_LLM_PROVIDER` で全体のデフォルト (``cai`` / ``anthropic`` / ``openai`` / ``bedrock``)。
Crew.ai の各 Agent は **role / Agent キーごと**に provider + model を上書きできる。

| レイヤ | env 例 | 用途 |
|---|---|---|
| デフォルト | `SOLOMON_LLM_PROVIDER` + 各 provider の API env | 未指定 role / Agent のフォールバック |
| **Role** | `SOLOMON_LLM_LIGHT_PROVIDER`, `SOLOMON_LLM_STRONG_PROVIDER`, `SOLOMON_LLM_EMBEDDING_PROVIDER` | light = Router / Inspector 等、strong = Summary / Dashboard、embedding = OpenSearch vector |
| **Model (role)** | `SOLOMON_LLM_ROUTER_MODEL` / `SOLOMON_LLM_ANALYTICS_MODEL`（別名 `SOLOMON_LLM_LIGHT_MODEL` / `SOLOMON_LLM_STRONG_MODEL`） | 同一 provider 内のモデル切替 |
| **Agent** | `SOLOMON_LLM_AGENT_<KEY>_PROVIDER`, `SOLOMON_LLM_AGENT_<KEY>_MODEL` | 例: `SUMMARY_WRITER`, `INTENT_CLASSIFIER`, `RAG_SYNTHESIS`（`AGENT_LLM_DEFAULT_ROLE` 参照） |

| Provider | 必須 env |
|---|---|
| `cai` | `CAI_INFERENCE_BASE_URL`, `CAI_INFERENCE_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY`（任意 `ANTHROPIC_BASE_URL`） |
| `openai` | `OPENAI_API_KEY`（任意 `OPENAI_BASE_URL`） |
| `bedrock` | `AWS_REGION` または `SOLOMON_AWS_REGION`（IAM role 前提） |

**例:** Router は CAI、Analytics は Anthropic — ``SOLOMON_LLM_LIGHT_PROVIDER=cai`` + CAI env、``SOLOMON_LLM_STRONG_PROVIDER=anthropic`` + ``ANTHROPIC_API_KEY``。

Embedding 既定モデル: `SOLOMON_LLM_EMBEDDING_MODEL`（provider 未指定時は `SOLOMON_LLM_PROVIDER` に従う）。

### 6. Cloudera Data Visualization (Deploy 後にプロジェクト内で有効化)

1. Cloudera AI Workbench の Data メニューから CDV を **Enable** する
   (プロジェクトごとに一度だけ実行が必要)
2. 有効化後に払い出された CDV endpoint URL を `SOLOMON_CDV_BASE_URL` に設定
3. Trino connection ID を CDV 側で用意している場合は `SOLOMON_CDV_TRINO_CONNECTION_ID`
   に設定 (省略可)

CDV 未設定でも取り込み・サマリー・RAG はそのまま動作する。ダッシュボード生成のみ
`CDV_NOT_CONFIGURED` エラーで停止し、ChatPane に SetupGuide カードが表示される。

### 反映方法

いずれの env も Project → Settings → Advanced → Environment Variables で追加した後、
同画面の **Application (Solomon) を Restart** することで反映される。

## API 概要

| パス | 用途 |
|---|---|
| `POST /api/wish` | SSE ストリーム (Router → Crew 実行、artifact イベント) |
| `GET /api/catalog/*` | Trino スキーマ / テーブル / カラム |
| `GET /api/files/*` | S3 ブラウズ / ファイルプレビュー |
| `GET /api/graph/schema` | Graph Node Labels / Relationship Types / Property Keys |
| `GET /api/graph/nodes?label=` | Label 指定でグラフ取得 |
| `GET /api/graph/relationships?type=` | Relationship Type 指定でグラフ取得 |
| `GET /api/graph/properties?key=` | Property Key 指定でグラフ取得 |
| `GET /api/graph/neighborhood/{id}` | ノード起点の N-hop 探索 (depth 1–3) |
| `GET /api/search/documents` | OpenSearch dataset カタログ (`solomon-datasets`、読み取り専用) |
| `POST /api/query` | Table Preview 用 SELECT |

## ライセンス

Apache-2.0
