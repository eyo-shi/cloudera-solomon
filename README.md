# Solomon

Cloudera AI Agent Studio 上で動作する自然言語データ分析マルチエージェント。ユーザーが日本語 / 英語で問い合わせるだけで **投入済み** Lakehouse / グラフ / Semantic Search を横断し、**テーブルサマリー生成 / Cloudera Data Visualization ダッシュボード作成 / ナレッジ横断検索 (Agentic RAG)** を実行する。3 ペイン Web UI (React + Vite) + FastAPI バックエンドを Cloudera AI Workbench の **AMP** (Application) として配信する。

**S3 → Iceberg / OpenSearch へのデータ取り込み**および **PuppyGraph 上の graph schema 定義**は別プロジェクトの責務とし、本リポジトリには含めない（デモ用の投入スクリプトのみ `demo/` に同梱）。

セマンティックレイヤは **Apache Ossie**（YAML 仕様）を採用し、`semantic/` 配下で Git 管理する。

## 構成

```
solomon/                   Python パッケージ (Crew + FastAPI)
  router/                  Router Crew (intent 分類 / ディスパッチ)
  rag/                     Agentic RAG (ReAct エージェント / 分類 / オーケストレーション / 合成)
  analytics/               Analytics Crew (サマリー / ダッシュボード)
  chat/                    一般会話 (CHITCHAT) 応答
  semantic/                Ossie 本家形式の読込・検索・集約コンテキスト
  graph/                   PuppyGraph (Bolt/openCypher) 接続・Schema ブラウズ (読み取り)
  opensearch/              OpenSearch (Cloudera Semantic Search) クライアント・文書検索
  trino/                   Trino 接続モード / endpoints 解決
  tools/                   CrewAI Tool 実装 (S3 / Trino / Graph Cypher / OpenSearch / Text2SQL 等)
  transport/               Knox JWT / UserContext / 設定解決 / LLM / HTTP / ロギング共通層
  infra/                   deploy.env 読み込み・デプロイモード判定
  manifest/                Agent Studio manifest 自動生成
  markdown/                チャット回答内の UI 深リンク (solomon://) 生成
  session/                 (予約・現状は空のスタブ)
  api/                     FastAPI (SSE ストリーム、静的 SPA 配信)

solomon_ui/                React + TypeScript + Vite (3 ペイン UI)
  src/panes/
    TreePane/              左: Knowledge Source Explorer (Tables / Storage / Graph / Search)
    ResultPane/            中央: Table / Dashboard / Summary / SQL / File / Graph のタブ
    ChatPane/              右: SSE ストリーム対応チャット

semantic/
  models/                  Apache Ossie セマンティックモデル (1 ファイル = 1 モデル)
  graph/schema.yaml        Knowledge Agent に渡すグラフ意味論
demo/                      デモ用データ生成・投入 (demo.loader)・検証 (demo.validate / demo.checks)
amp/                       AMP セットアップタスク (依存導入 / UI ビルド / 起動 等) と Runtime Dockerfile
1_start-opensearch/        OpenSearch Launcher (OPENSEARCH_MODE=internal)
1_start-warehouse/         Warehouse Launcher — Trino + DuckDB (TRINO_MODE=internal)
1_start-puppygraph/        PuppyGraph Launcher (PUPPYGRAPH_MODE=internal)
utils/, warehouse/         Launcher の実装
deploy/deploy.env.example  .solomon/deploy.env のテンプレート
docs/                      Air-gap / S3 接続ガイド
scripts/                   補助スクリプト (manifest 生成、ドメイン中立チェック 等)
tests/                     pytest
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

左ペイン (TreePane) でタブを切り替える。

- **Tables**: テーブルを選択すると、中央ペインに Table Preview を表示する。
- **Graph**: Node Label / Relationship Type / Property Key をクリックすると、中央ペインに **Cytoscape** でグラフを可視化する。
- **Search**: インデックス済みドキュメントの一覧を表示する。

## Agentic RAG

自然言語のナレッジ質問は Router が `KNOWLEDGE_RAG` intent に振り分ける。

**既定 (`SOLOMON_RAG_ENGINE=agent`)** — ReAct 型 **Knowledge Agent**（最大 8 手）が `sql_query` / `graph_query` / `doc_search` を litellm 経由で自律的に組み合わせ、SQL・グラフ・文書を横断して回答する。

- グラフの意味論は `SOLOMON_GRAPH_SCHEMA_FILE`（既定 `semantic/graph/schema.yaml`）から読み込み、システムプロンプトに含める。
- LLM は `rag_agent`（strong ロール。`SOLOMON_LLM_AGENT_RAG_AGENT_*` で上書き可）。
- ツール呼び出し形式は `SOLOMON_RAG_TOOL_MODE=auto|native|json`。

**heuristic (`SOLOMON_RAG_ENGINE=heuristic`)** — 従来どおり正規表現で戦略を 1 つ選び、固定パイプラインを 1 回実行する。

**ソース構成** — `table` / `graph` / `search` をリクエストごとに ON/OFF できる（`POST /api/wish` の `sources`。省略時は `SOLOMON_RAG_SOURCES`）。Chat の 4 択（テーブルのみ / ＋Graph / ＋Search / 全部）で切り替えられ、再起動は不要。

| 戦略 (heuristic) | 主なソース |
|---|---|
| `GRAPH_QUERY` | PuppyGraph (Lakehouse/RDB 上の graph schema) |
| `SQL_ANALYTICS` | Ossie + OpenSearch コンテキスト → Trino Text2SQL |
| `KEYWORD` / `HYBRID` | OpenSearch (BM25 / k-NN / RRF) |
| `COMPOSITE` | 上記の組み合わせ |

heuristic モードで graph ヒットがある場合は、中央ペインに Graph 可視化タブを自動で開く（agent モードでは未対応）。

## PuppyGraph

Graph タブは PuppyGraph の Bolt (7687) に接続し、`CALL db.labels()` 等でスキーマを取得する。Label / Relationship / Property Key をクリックすると、API 側で openCypher を生成・実行する。Iceberg / PostgreSQL 等の catalog と graph schema は **PuppyGraph 側**で管理する。

## 実装ステータス

MVP + Knowledge Source 拡張が `main` に入っている:

| モジュール | 内容 |
|---|---|
| `solomon.transport` | Knox JWT / user_context / 設定解決 / LLM factory / HTTP client / structlog / `BaseSolomonTool` |
| `solomon.tools` | S3 / Trino / フォーマット判定 / Excel ヘッダー検出 / CDV / Graph Cypher / OpenSearch / Text2SQL |
| `solomon.graph` | PuppyGraph Bolt 接続、Schema ブラウズ (`browse.py`) |
| `solomon.opensearch` | OpenSearch 接続 (Data Hub Semantic Search / internal launcher)、keyword / vector / hybrid 検索、文書検索 |
| `solomon.rag` | Agentic RAG (ReAct agent / classifier / orchestrator / synthesizer) |
| `solomon.analytics.AnalyticsCrew` | Summary パス (2 タスク) + Dashboard パス (4 タスク、VizPlanner + CDV) |
| `solomon.router.RouterCrew` | intent 分類 + Python レベルディスパッチ (`KNOWLEDGE_RAG` 含む) |
| `solomon.api` | FastAPI (`/api/wish` SSE ほか。[API 概要](#api-概要)参照) |
| `solomon_ui` | React + Vite 3 ペイン UI (4 Knowledge Source タブ + Graph 可視化 + ChatPane SSE) |
| `solomon.manifest` | Python 定義から Agent Studio manifest を自動生成 |
| `.project-metadata.yaml` | Cloudera AI Workbench (AMP) 登録用マニフェスト |

未着手 (v2 候補): TablePreview の仮想スクロール、Graph 2-hop/3-hop UI、Ossie バッジの実 YAML 判定、セッション履歴の hydrate、Analytics の Hierarchical Process 移行。

## 開発

CDW + Iceberg / PuppyGraph / OpenSearch の**デモ環境構築・リハーサル**は [demo/SETUP.md](demo/SETUP.md) を参照（`demo.loader` / `demo.validate` / `demo.checks.preflight`）。

### バックエンド

Python **3.12** 以上が必要。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest             # テスト
cp .env.example .env   # 値を編集
uvicorn solomon.api.main:app --reload --env-file .env   # http://127.0.0.1:8000
```

ローカル開発時の注意:

- **`.env` はアプリが自動では読まない。** 上記のように `uvicorn --env-file .env` を指定するか、同じ内容を `.solomon/deploy.env` に置く（カレントディレクトリ基準で起動時に読み込まれる）。
- `python -m solomon.api.main` / `solomon-api` で起動すると port は `SOLOMON_API_PORT`（既定 **8080**）になり、Vite のプロキシ先 (8000) と一致しない。UI と組み合わせる場合は上記の `uvicorn` コマンドを使う。
- Tables / Storage / Graph / Search / Query の API は Knox 認証が必須で、Knox を経由しないローカル環境では **401 `AUTH_MISSING`** を返す。curl で確認する場合は `Authorization: Bearer <JWT>` を付与する。外部 Trino をローカルから使う場合は `TRINO_USER` / `TRINO_PASSWORD`（Basic 認証）も設定する。

### フロントエンド

```bash
cd solomon_ui
npm ci             # package-lock.json 必須 (リポジトリ同梱)
npm run dev        # http://localhost:5173  (API は /api を 127.0.0.1:8000 にプロキシ)
npm run build      # solomon/api/static/ に SPA を出力
```

Graph 可視化には **cytoscape** を使用する (`npm ci` で自動インストール)。

### Cloudera AI Workbench (AMP) で配信

AMP Deploy では `.project-metadata.yaml` のタスクが上から順に実行される。

1. Python 依存のインストール (`amp/01_install_python_deps.py`)
2. UI ビルド — nvm + `npm ci && npm run build` (`amp/02_build_ui.py`)
3. `semantic/` の準備 (`amp/03_seed_semantic.py`)
4. Agent Studio manifest の drift 検証 (`amp/04_verify_manifest.py`)
5. 3 つの Launcher (OpenSearch / Warehouse / PuppyGraph) を Application として起動 (external モードでは no-op)
6. `.solomon/deploy.env` の生成 (`amp/06_ensure_deploy_env.py`)
7. Solomon 本体を Application として起動 (`amp/05_start_application.py`)

手動でビルド・起動する場合:

1. `cd solomon_ui && npm ci && npm run build`
2. Workbench Application として `python -m solomon.api.main` を起動 (`CDSW_APP_PORT` で listen する)
3. FastAPI が `/api/*` と `/` (SPA) を配信する

## Deploy フォーム (AMP Configuration 画面)

Deploy 時に Configuration 画面へ表示される Environment Variables（すべて optional。デフォルト値は `.project-metadata.yaml` の定義）:

| 変数 | デフォルト | 説明 |
|---|---|---|
| `SOLOMON_LOG_LEVEL` | `INFO` | ログレベル |
| `TRINO_MODE` | `external` | `external` = CDW Trino ／ `internal` = warehouse-launcher (Trino + DuckDB デモ) |
| `PUPPYGRAPH_MODE` | `internal` | `internal` = puppygraph-launcher ／ `external` = 外部 PuppyGraph Bolt |
| `OPENSEARCH_MODE` | `external` | `external` = Semantic Search 等の外部クラスタ ／ `internal` = opensearch-launcher |

接続先 URI・認証情報・LLM・CDV は Deploy フォームには出さず、Deploy 後に設定する（次節）。
PuppyGraph の `PUPPYGRAPH_URI` も Deploy フォームには出さない（`.solomon/deploy.env` で設定）。

launcher のメモリ・PVC・イメージ等のチューニング（`TRINO_MEMORY`、`OPENSEARCH_MEMORY`、`PUPPYGRAPH_IMAGE` など）も Deploy フォームには出さない。
必要な場合のみ Deploy 後に **Project → Settings → Advanced → Environment Variables** で設定する（`.env.example` の optional セクション参照）。

Air-gap 環境で AMP Deploy する場合（Runtime / UI / launcher イメージの mirror）は
[docs/airgap_amp.md](docs/airgap_amp.md) を参照。

## Deploy 後の設定手順 (Post-Deploy Configuration)

Post-deploy 設定の **正本** はプロジェクト永続領域の **`.solomon/deploy.env`**（dotenv 形式）。
AMP Deploy 時に `amp/06_ensure_deploy_env.py` が、ファイルが無ければ `deploy/deploy.env.example` から生成する（既存ファイルは上書きしない）。
秘匿情報だけを **`.solomon/secrets.env`**（Git 除外）に分けてもよい。

Application の起動時（`amp/05_start_application.py` / `python -m solomon.api.main`）に、これらのファイルの内容が `os.environ` へマージされる。
変更後は **Solomon Application を Restart** すると反映される。

### 優先順位

既定では、ファイルは **未設定または空のキーだけ** を埋める。

| 優先度 | 設定源 |
|--------|--------|
| 高 | Project 環境変数のうち **非空** の値（Project → Settings → Environment Variables、および **AMP Configuration 画面で確定した値**） |
| 中 | `.solomon/deploy.env` |
| 低 | `.solomon/secrets.env`（deploy.env にも同じキーがあると、そちらが先に埋めるため反映されない） |

- AMP フォームの値（デフォルトのまま進めた `TRINO_MODE=external` 等も含む）は Project 環境変数になるため、**deploy.env に同じキーを書いても反映されない**。モードを後から変える場合は、Project Settings の値を書き換えるか、下記の override を使う。
- deploy.env と secrets.env に同じキーを書かないこと（秘匿値は secrets.env だけに書く）。
- **Project 環境変数**に `SOLOMON_DEPLOY_ENV_OVERRIDE=true` を設定すると、ファイルに書かれた非空の値が既存の環境変数を上書きする（この判定はファイルの読み込み前に行われるため、deploy.env に書いても効かない）。その場合は deploy.env → secrets.env の順に適用され、secrets.env が優先される。`CDSW_*` / `CML_*` 等のプラットフォーム注入キーは常に除外される。

**external** モードでは、Trino / OpenSearch / PuppyGraph の接続先、および LLM / CDV を上記ファイルに記載する。
S3 と OpenSearch は **Site Administration → Data Connections** の接続も利用できる（Trino は env のみ）。

未設定のまま UI で該当機能を使うと、API は HTTP 503 + JSON (`{error_code, message, instruction}`) を返し、UI の **SetupGuide カード** が設定手順を表示する。

### 最小構成で必要な環境変数

Solomon は環境変数が 1 つも無くても起動する（未設定の機能だけが 503 で止まる）。機能ごとに必要な変数:

| 機能 | 必要な変数 |
|---|---|
| チャット全般 (Router / RAG / Analytics) | `SOLOMON_LLM_PROVIDER` + provider ごとの認証 env（[§5](#5-llm-プロバイダ)） |
| Tables（`TRINO_MODE=external`） | `TRINO_URL` または `TRINO_HOST` |
| Search（`OPENSEARCH_MODE=external`） | `OPENSEARCH_CONNECTION_NAME` または `OPENSEARCH_ENDPOINT`（Data Connection が自動検出できれば不要） |
| Graph（`PUPPYGRAPH_MODE=external`） | `PUPPYGRAPH_URI` |
| Storage | `SOLOMON_S3_BUCKETS` + `SOLOMON_IDBROKER_URL`（または S3 Data Connection） |
| ダッシュボード | `SOLOMON_CDV_BASE_URL` |

internal モードの Tables / Search / Graph は、各 launcher が書き出す `.solomon/*_endpoints.json` から接続先を自動で解決するため、追加の設定は不要。

### 1. Trino / Tables への接続

Deploy 時に `TRINO_MODE` で接続方式を切り替える（デフォルト `external`）。

| モード | 用途 | 設定 |
|---|---|---|
| `external` (デフォルト) | 本番 CDW | Application env の `TRINO_URL` または `TRINO_HOST` 等（下記。Data Connection は使わない） |
| `internal` | CML 内部デモ | `warehouse-launcher` が Trino + DuckDB (catalog `iceberg`) を 1 Pod で起動 |

**external (`TRINO_MODE=external`)**

`.solomon/deploy.env`（または Project 環境変数）に設定する:

- **接続先**（いずれか）: `TRINO_URL`（推奨・1 行）、または `TRINO_HOST` + `TRINO_PORT` (443) + `TRINO_SCHEME` (https)
- `TRINO_VERIFY_SSL` (default `true`。CA bundle のパスも可)
- `TRINO_CATALOG` (default `iceberg`)
- `TRINO_SCHEMA` (default `demo`)
- **認証**: 既定は UI ログインユーザーの **Knox JWT**。Basic 認証を使う場合は
  `TRINO_USER` + `TRINO_PASSWORD`（`TRINO_AUTH=auto` のときは password があれば Basic になる）

旧名 `SOLOMON_TRINO_*` も後方互換で読み取る。

**internal (`TRINO_MODE=internal`)**

- AMP Deploy で `warehouse-launcher` が起動する
- `demo` スキーマに `customers` / `orders` を seed する（Tables タブですぐ確認できる）
- カタログ名は `iceberg` だが、実体は DuckDB（Iceberg テーブルではない）
- Solomon は `.solomon/trino_endpoints.json` から HTTP 接続先を自動で解決する
- DNS が通らない場合のみ、post-deploy で `TRINO_ENDPOINT` を設定する

### 2. S3 への接続

詳細: [docs/s3_connectivity.md](docs/s3_connectivity.md)

- **推奨 (CDP on AWS)**: `SOLOMON_IDBROKER_URL` + ログインユーザーの Knox JWT → STS。
  **S3 が Data Connections に無くても動く**（新しい環境で S3 タイプが出ない場合はこちら）。
- **Storage タブ**: `SOLOMON_S3_BUCKETS` に実在するバケット名を設定する（カンマ区切り）。未設定の場合は `demo-bucket` が表示され、チャット添付のアップロードもできない。
- **IDBroker 未設定時のみ**: S3 Data Connection（`SOLOMON_S3_CONNECTION_NAME`、または自動検出）を使う。
- リージョンは `AWS_REGION`（default `us-east-1`。Data Connection に region があればそちらを優先）。AMP に AWS access key は置かない。
- MinIO などのカスタム endpoint は `SOLOMON_S3_ENDPOINT_URL`。

トラブルシュート: ログイン後に `GET /api/files/diagnostics`。

### 3. PuppyGraph (Graph / openCypher)

Graph タブと `graph_cypher_query` Tool は **PuppyGraph Bolt (7687)** に接続する。

Deploy 時に `PUPPYGRAPH_MODE` を選ぶ（デフォルト `internal`）。

| モード | 用途 | 設定 |
|---|---|---|
| `internal` (デフォルト) | CML 内部 | `puppygraph-launcher` が K8s 上で PuppyGraph を起動し、`.solomon/puppygraph_endpoints.json` を Solomon と共有 |
| `external` | 外部 PuppyGraph | `.solomon/deploy.env` に `PUPPYGRAPH_URI=bolt://host:7687` |

**internal (`PUPPYGRAPH_MODE=internal`)**

- AMP Deploy で `puppygraph-launcher` が起動する（K8s 上で **PuppyGraph コンテナイメージ**を pull。既定は `puppygraph/puppygraph:1.15.0`、`PUPPYGRAPH_IMAGE` で変更可）
- Bolt が ready になると `.solomon/puppygraph_endpoints.json` を自動で更新する
- その後 **Solomon Application を Restart** すると、Graph タブと RAG の graph 検索が有効になる
- DNS が通らない場合のみ、post-deploy で `PUPPYGRAPH_URI=bolt://<ClusterIP>:7687` を設定する
- Iceberg / Trino catalog と graph schema は **PuppyGraph Web UI**（Pod 8081 / in-cluster）で定義する。Solomon からはアップロードしない

**共通**

- 認証: `PUPPYGRAPH_USERNAME` / `PUPPYGRAPH_PASSWORD`（既定 `puppygraph` / `puppygraph123`。`secrets.env` に置いてよい。internal では launcher Pod と Solomon で同じ値にする）
- `GET /api/graph/meta` で接続できるか確認できる

接続先が解決できない場合、Graph タブと Agentic RAG の graph 検索は `GRAPH_NOT_CONFIGURED` で停止する。

### 4. OpenSearch / Semantic Search への接続

Deploy 時に `OPENSEARCH_MODE` で接続方式を切り替える（デフォルト `external`）。
Solomon のプロセス内では OpenSearch サーバーは起動しない。

| モード | 用途 | 設定 |
|---|---|---|
| `external` (デフォルト) | 外部クラスタ | Data Hub **Semantic Search for AWS** 等。Data Connection または env で接続 |
| `internal` | CML 内部 | `opensearch-launcher` が K8s 上で OpenSearch を起動し、`.solomon/opensearch_endpoints.json` を Solomon と共有 |

**external (`OPENSEARCH_MODE=external`)**

- launcher は no-op
- Data Connections に OpenSearch connection を登録済みなら `OPENSEARCH_CONNECTION_NAME` を設定する（省略時は OpenSearch タイプの connection を自動検出）
- 直接指定する場合: `OPENSEARCH_ENDPOINT`（別名 `OPENSEARCH_URL` / `OPENSEARCH_HOST`）、`OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD`、`OPENSEARCH_NAMESPACE`（default `solomon`）など

**internal (`OPENSEARCH_MODE=internal`)**

- AMP Deploy で `opensearch-launcher` が起動する
- OpenSearch の起動後に `solomon-datasets` インデックスを自動で作成する（Solomon の起動時にも再試行する）
- **OpenSearch Dashboards** を同じ Pod で起動し、Launcher Application URL の `/dashboards/` から使える
- HTTP エンドポイントは Application Log に出力される
- DNS が通らない場合は、post-deploy で `OPENSEARCH_ENDPOINT` を設定する

**インデックス**

- dataset カタログ: `OPENSEARCH_INDEX`（default `{namespace}-datasets` = `solomon-datasets`）
- 業務文書チャンク: `OPENSEARCH_DOCS_INDEX`（default は Ossie の `document_index` 定義、無ければ `{namespace}-docs`）
- Search タブの表示対象: `OPENSEARCH_SEARCH_SCOPE=datasets|docs|both`（default `datasets`）

インデックスへのデータ投入は別プロジェクトの責務（デモでは `demo.loader`）。
接続先が解決できない場合、Search タブと RAG の keyword/hybrid 検索は `OPENSEARCH_NOT_CONFIGURED` で停止する。

### 5. LLM プロバイダ

**既定:** `SOLOMON_LLM_PROVIDER` で全体のデフォルトを指定する（`cai` / `anthropic` / `openai` / `bedrock`）。未指定でも `CAI_INFERENCE_BASE_URL` と `CAI_INFERENCE_API_KEY` がそろっていれば `cai` を使う。
Crew.ai の各 Agent は、**role / Agent キーごと** に provider と model を上書きできる。

| レイヤ | env 例 | 用途 |
|---|---|---|
| デフォルト | `SOLOMON_LLM_PROVIDER` + 各 provider の API env | 未指定の role / Agent のフォールバック |
| **Role** | `SOLOMON_LLM_LIGHT_PROVIDER`, `SOLOMON_LLM_STRONG_PROVIDER`, `SOLOMON_LLM_EMBEDDING_PROVIDER` | light = Router / Inspector 等、strong = Summary / Dashboard / RAG、embedding = OpenSearch vector |
| **Model (role)** | `SOLOMON_LLM_ROUTER_MODEL` / `SOLOMON_LLM_ANALYTICS_MODEL`（別名 `SOLOMON_LLM_LIGHT_MODEL` / `SOLOMON_LLM_STRONG_MODEL`）、`SOLOMON_LLM_EMBEDDING_MODEL` | 同じ provider 内でのモデル切り替え（未指定時は provider ごとの既定モデル） |
| **Agent** | `SOLOMON_LLM_AGENT_<KEY>_PROVIDER`, `SOLOMON_LLM_AGENT_<KEY>_MODEL` | 例: `SUMMARY_WRITER`, `INTENT_CLASSIFIER`, `RAG_SYNTHESIS`, `RAG_AGENT`（キー一覧は `solomon/transport/config.py` の `AGENT_LLM_DEFAULT_ROLE`） |

| Provider | 必須 env |
|---|---|
| `cai` | `CAI_INFERENCE_BASE_URL`, `CAI_INFERENCE_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY`（任意で `ANTHROPIC_BASE_URL`） |
| `openai` | `OPENAI_API_KEY`（任意で `OPENAI_BASE_URL`） |
| `bedrock` | `AWS_REGION` または `SOLOMON_AWS_REGION`（IAM role 前提） |

**例:** Router は CAI、Analytics は Anthropic にする場合は、`SOLOMON_LLM_LIGHT_PROVIDER=cai` + CAI の env、`SOLOMON_LLM_STRONG_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` を設定する。

Embedding モデルは `SOLOMON_LLM_EMBEDDING_MODEL`（provider は `SOLOMON_LLM_EMBEDDING_PROVIDER`、未指定時は `SOLOMON_LLM_PROVIDER` に従う）。

設定状況は `GET /api/setup/llm` で確認できる（未設定なら 503）。

### 6. Cloudera Data Visualization (Deploy 後にプロジェクト内で有効化)

1. Cloudera AI Workbench の Data メニューから CDV を **Enable** する
   （プロジェクトごとに一度だけ必要）
2. 有効化後に払い出された CDV の endpoint URL を `SOLOMON_CDV_BASE_URL` に設定する
3. CDV 側で Trino connection を用意している場合は、その ID を `SOLOMON_CDV_TRINO_CONNECTION_ID` に設定する（省略可）

CDV が未設定でも、サマリーと RAG はそのまま動作する。ダッシュボード生成だけが
`CDV_NOT_CONFIGURED` エラーで停止し、ChatPane に SetupGuide カードが表示される。

### 反映方法

1. `.solomon/deploy.env`（秘匿値は `.solomon/secrets.env`）を編集する。
   緊急時やファイルを上書きしたい場合は、Project → Settings → Advanced → Environment Variables で設定する（[優先順位](#優先順位)参照）。
2. **Application (Solomon) を Restart** する。

## API 概要

| パス | 用途 |
|---|---|
| `POST /api/wish` | SSE ストリーム (Router → Crew 実行、artifact イベント) |
| `GET /api/catalog/{schemas,tables,columns}` | Trino スキーマ / テーブル / カラム |
| `POST /api/query` | Table Preview 用 SELECT |
| `GET /api/files/{buckets,list,preview,raw}` | S3 ブラウズ / ファイルプレビュー / 生データ |
| `POST /api/files/upload` | Chat 添付ファイルを S3 にアップロード |
| `GET /api/files/diagnostics` | S3 接続トラブルシュート |
| `GET /api/graph/meta` | PuppyGraph 接続状態 |
| `GET /api/graph/schema` | Graph Node Labels / Relationship Types / Property Keys |
| `GET /api/graph/nodes?label=` | Label を指定してグラフを取得 |
| `GET /api/graph/relationships?type=` | Relationship Type を指定してグラフを取得 |
| `GET /api/graph/properties?key=` | Property Key を指定してグラフを取得 |
| `GET /api/graph/neighborhood/{id}` | ノードを起点にした N-hop 探索 (depth 1–3) |
| `GET /api/graph/entity?hint=` / `GET /api/graph/overview` | エンティティ検索 / 全体俯瞰 |
| `POST /api/graph/cypher` | openCypher 実行 (読み取り) |
| `GET /api/search/documents` | Search タブの一覧 (`scope=datasets\|docs\|both`) |
| `GET /api/search/document` / `GET /api/search/doc` | dataset / 業務文書の詳細 (Chat の深リンク用) |
| `GET /api/search/diagnostics` | OpenSearch 接続トラブルシュート |
| `GET /api/ossie/{name}` / `GET /api/semantic/context` | Ossie モデル / 業務コンテキスト |
| `GET /api/artifacts/{id}` / `GET /api/sessions/{id}` | 生成済み artifact / セッション |
| `GET /api/setup/llm` | LLM 設定チェック |
| `GET /healthz` | ヘルスチェック |

catalog / query / files / graph / search の各 API は Knox 認証が必須（未認証の場合は 401）。

## ライセンス

Apache-2.0
