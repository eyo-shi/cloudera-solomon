# Solomon

Cloudera AI Agent Studio 上で動作する自然言語データ分析マルチエージェント。ユーザーが日本語 / 英語で問い合わせるだけで **S3 → Iceberg 取り込み / Neo4j グラフDBへのノード・リレーション追加 / OpenSearch インデックス投入 / テーブルサマリー生成 / Cloudera Data Visualization ダッシュボード作成 / ナレッジ横断検索 (Agentic RAG)** を一気通貫に実行する。3 ペイン Web UI (React + Vite) + FastAPI バックエンドを Cloudera AI Workbench Application として配信する。

セマンティックレイヤは **Apache Ossie**（YAML 仕様）を採用し、`semantic/` 配下で Git 管理する。

## 構成

```
solomon/           Python パッケージ (Crew + FastAPI)
  router/       Router Crew (intent 分類 / ディスパッチ)
  ingestion/    Ingestion Crew (S3 → Iceberg → Neo4j → Ossie → OpenSearch)
  graph/        Neo4j 接続・グラフ投入・Schema ブラウズ API
  opensearch/   外部 OpenSearch (Cloudera Semantic Search) クライアント
  rag/          Agentic RAG (分類 / オーケストレーション / 合成)
  analytics/    Analytics Crew (サマリー / ダッシュボード)
  semantic/     Ossie YAML 読み書き / 検索
  session/      セッション、リクエスト、メモリ
  transport/    Knox JWT / HTTP / ロギング共通層
  tools/        CrewAI Tool 実装 (S3 / Trino / Neo4j / OpenSearch / Text2SQL 等)
  api/          FastAPI (SSE ストリーム、静的 SPA 配信)
  demo/         デモ用ウォームアップ

solomon_ui/        React + TypeScript + Vite (3 ペイン UI)
  src/panes/
    TreePane/   左: Knowledge Source Explorer (Tables / Storage / Graph / Search)
    ResultPane/ 中央: Table / Dashboard / Summary / SQL / File / Graph のタブ
    ChatPane/   右: SSE ストリーム対応チャット

semantic/       Apache Ossie YAML の Git 管理領域
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
| **Graph** | Graph | Neo4j (`/api/graph/*`) | リネージ・System/Dataset/Document 関係の探索 |
| **Semantic Search** | Search | OpenSearch (`/api/search/*`) | ベクトル + キーワード検索インデックス |

左ペイン (TreePane) でタブを切り替え、Tables ではテーブル選択 → 中央ペインに Table Preview、Graph では Node Label / Relationship Type / Property Key をクリック → 中央ペインに **Cytoscape** グラフ可視化、Search ではインデックス済みドキュメント一覧を表示する。

## Agentic RAG

自然言語のナレッジ質問は Router が `KNOWLEDGE_RAG` intent に振り分け、以下の戦略で複数ソースを横断検索する。

| 戦略 | 主なソース |
|---|---|
| `GRAPH_QUERY` | Neo4j (System / Dataset / Document / リネージ) |
| `SQL_ANALYTICS` | Ossie + OpenSearch コンテキスト → Trino Text2SQL |
| `KEYWORD` / `HYBRID` | OpenSearch (BM25 / k-NN / RRF) |
| `COMPOSITE` | 上記の組み合わせ |

RAG 実行後、Neo4j ヒットがある場合は中央ペインに Graph 可視化タブを自動で開く。

## Neo4j グラフスキーマ

Ingestion 時に以下のノード・リレーションが投入される。

**Labels:** `System`, `Document`, `Dataset`, `Column`, `SourceFile`, `Schema`, `MetadataEntry`

**Relationships:** `OWNS_DATASET`, `HAS_DOCUMENT`, `REFERENCES_DATASET`, `HAS_COLUMN`, `IN_SCHEMA`, `SOURCED_FROM`, `HAS_METADATA`

Graph タブでは `CALL db.labels()` 等でスキーマを取得し、Label / Relationship / Property Key クリックで Cypher を API 側が生成・実行する (フロントエンドに Cypher をハードコードしない)。

## 実装ステータス

MVP + Knowledge Source 拡張が `main` に入っている:

| モジュール | 内容 |
|---|---|
| `solomon.transport` | Knox JWT / user_context / HTTP client / structlog / `BaseSolomonTool` |
| `solomon.tools` | S3 / Trino / フォーマット判定 / Excel ヘッダー検出 / CDV / Neo4j Query / OpenSearch / Text2SQL |
| `solomon.ingestion.IngestionCrew` | S3 → Iceberg → Neo4j → Ossie → OpenSearch の 10 タスク Sequential パイプライン |
| `solomon.graph` | Neo4j 接続 (CML neo4j-launcher 対応)、グラフ投入、Schema ブラウズ (`browse.py`) |
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
| `TRINO_MODE` | `internal` | Trino / Tables: warehouse-launcher (DuckDB) / CDW |
| `NEO4J_MODE` | `internal` | Neo4j: CML 内 launcher / 外部クラスタ |
| `NEO4J_USERNAME` | `neo4j` | Neo4j 認証ユーザー (launcher と Solomon が共有) |
| `NEO4J_PASSWORD` | `Neo4jPass1234` | Neo4j 認証パスワード (本番では必ず変更) |
| `OPENSEARCH_MODE` | `internal` | OpenSearch: CML 内 launcher / 外部クラスタ |

launcher のメモリ・PVC 等のチューニングは Deploy フォームには出さない。
必要な場合のみ Deploy 後に **Project → Settings → Advanced → Environment Variables**
で設定する (`.env.example` の optional セクション参照)。

## Deploy 後の設定手順 (Post-Deploy Configuration)

**external** を選んだ場合は Deploy 後に **Project → Settings → Advanced →
Environment Variables** で接続情報を設定する。Trino / S3 は **Site Administration → Data
Connections** が single source of truth。LLM / CDV も Deploy 後に同画面で設定し、Application を
再起動して反映する。

未設定のまま UI で該当機能を叩くと、API は HTTP 503 + JSON (`{error_code, message,
instruction}`) を返し、UI の **SetupGuide カード** が手順を表示する。

### 1. Trino / Tables への接続

Deploy 時に `TRINO_MODE` で接続方式を切り替える (デフォルト `internal`)。

| モード | 用途 | 設定 |
|---|---|---|
| `internal` (デフォルト) | CML 内部デモ | `warehouse-launcher` が Trino + DuckDB (catalog `iceberg`) を 1 Pod で起動 |
| `external` | 本番 CDW | Data Connection または `TRINO_HOST` 等 (下記) |

**internal (`TRINO_MODE=internal`)**

- AMP Deploy で `warehouse-launcher` が起動
- `demo` スキーマに `customers` / `orders` を seed (Tables タブですぐ確認可能)
- Solomon は `.solomon/trino_endpoints.json` から HTTP 接続先を自動解決
- DNS が通らない場合のみ `TRINO_ENDPOINT` を post-deploy で設定

**external (`TRINO_MODE=external`)**

- Site Administration → Data Connections で CDW / Trino connection を登録済みなら、
  `TRINO_CONNECTION_NAME` にその connection 名を設定する
  (未設定でも Trino タイプの connection が 1 個なら自動採用)。
- Data Connections を使わない環境では以下を代わりに設定:
  - `TRINO_HOST`
  - `TRINO_PORT` (default 443)
  - `TRINO_SCHEME` (default `https`)
  - `TRINO_VERIFY_SSL` (default `true`)
  - `TRINO_CATALOG` (default `iceberg`)
  - `TRINO_SCHEMA` (default `demo`)

旧名 `SOLOMON_TRINO_*` も後方互換で読み取る。

### 2. S3 への接続

- Site Administration → Data Connections で S3 connection を登録済みなら、
  `SOLOMON_S3_CONNECTION_NAME` を設定 (省略時は S3 タイプの最初の connection を自動採用)。
- Data Connections を使わない環境では `SOLOMON_AWS_REGION` (default `us-east-1`)。
- 認証情報は IDBroker STS 経由でユーザー単位に払い出されるため、AMP には
  AWS access key / secret は一切保持しない。

### 3. Neo4j への接続

Deploy 時に `NEO4J_MODE` で接続方式を切り替える (デフォルト `internal`)。

| モード | 用途 | 設定 |
|---|---|---|
| `internal` (デフォルト) | CML 内部 | `neo4j-launcher` が K8s 上で Neo4j を起動し、`.solomon/neo4j_endpoints.json` を Solomon と共有 |
| `external` | 外部クラスタ | Deploy フォームで `NEO4J_USERNAME` / `NEO4J_PASSWORD` を設定。Deploy 後に `NEO4J_URI` を Project Settings で設定 |

**internal (`NEO4J_MODE=internal`)**

- AMP Deploy で `neo4j-launcher` が起動
- Solomon は endpoints file から Bolt URI を自動解決 (Deploy 時に `NEO4J_URI` は不要)
- Internal DNS が通らない場合のみ `NEO4J_URI` または `NEO4J_EXTERNAL_URI` を post-deploy で設定

**external (`NEO4J_MODE=external`)**

- launcher は no-op。外部 Neo4j クラスタへ直接接続
- Project Settings → Advanced → Environment Variables に接続情報を設定

未設定時は Graph タブ・Ingestion の Neo4j 書込・Agentic RAG の graph 検索が
`NEO4J_NOT_CONFIGURED` で停止する。

### 4. OpenSearch / Semantic Search への接続

Deploy 時に `OPENSEARCH_MODE` で接続方式を切り替える (デフォルト `internal`)。
Solomon プロセス内では OpenSearch サーバーは起動しない。

| モード | 用途 | 設定 |
|---|---|---|
| `internal` (デフォルト) | CML 内部 | `opensearch-launcher` が K8s 上で OpenSearch を起動し、`.solomon/opensearch_endpoints.json` を Solomon と共有 |
| `external` | 外部クラスタ | Data Hub **Semantic Search for AWS** 等 — Data Connection または env で接続 |

**internal (`OPENSEARCH_MODE=internal`)**

- AMP Deploy で `opensearch-launcher` が起動 (Neo4j launcher と同型)
- OpenSearch 起動後に `solomon-datasets` インデックスを自動作成 (Solomon 起動時も再試行)
- **OpenSearch Dashboards** を同 Pod で起動し、Launcher Application URL の `/dashboards/` から利用 (Neo4j Browser 相当)
- Application Log に HTTP エンドポイントが出力される
- DNS が通らない場合は `OPENSEARCH_ENDPOINT` を post-deploy で設定

**external (`OPENSEARCH_MODE=external`)**

- launcher は no-op
- Data Connections に OpenSearch connection を登録済みなら
  `OPENSEARCH_CONNECTION_NAME` を設定 (省略時は OpenSearch タイプを自動検出)
- 直接指定: `OPENSEARCH_ENDPOINT`, `OPENSEARCH_NAMESPACE`, 認証情報など

Ingestion 完了後に Ossie dataset が OpenSearch にインデックスされる。
未設定時は Search タブ・RAG の keyword/hybrid 検索が `OPENSEARCH_NOT_CONFIGURED` で停止する。

### 5. LLM プロバイダ (以下いずれか 1 つを選択)

| `SOLOMON_LLM_PROVIDER` | 必須 env | 任意 env |
|---|---|---|
| `cai` (default) | `CAI_INFERENCE_BASE_URL`, `CAI_INFERENCE_API_KEY` | `SOLOMON_LLM_ROUTER_MODEL` (default `llama-3-8b-instruct`), `SOLOMON_LLM_ANALYTICS_MODEL` (default `llama-3-70b-instruct`) |
| `anthropic` | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL`, `SOLOMON_LLM_ROUTER_MODEL` (default `claude-haiku-4-5-20251001`), `SOLOMON_LLM_ANALYTICS_MODEL` (default `claude-sonnet-4-5-20250929`) |
| `openai` | `OPENAI_API_KEY` | `OPENAI_BASE_URL`, `SOLOMON_LLM_ROUTER_MODEL` (default `gpt-4o-mini`), `SOLOMON_LLM_ANALYTICS_MODEL` (default `gpt-4o`) |
| `bedrock` | `AWS_REGION` (or `SOLOMON_AWS_REGION`, IAM role 前提) | `SOLOMON_LLM_ROUTER_MODEL`, `SOLOMON_LLM_ANALYTICS_MODEL` |

ベクトル検索用 embedding には `SOLOMON_LLM_EMBEDDING_MODEL` (default `bge-m3`) を使用する。

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
| `GET /api/graph/schema` | Neo4j Node Labels / Relationship Types / Property Keys |
| `GET /api/graph/nodes?label=` | Label 指定でグラフ取得 |
| `GET /api/graph/relationships?type=` | Relationship Type 指定でグラフ取得 |
| `GET /api/graph/properties?key=` | Property Key 指定でグラフ取得 |
| `GET /api/graph/neighborhood/{id}` | ノード起点の N-hop 探索 (depth 1–3) |
| `GET /api/search/documents` | OpenSearch インデックス済みドキュメント |
| `POST /api/query` | Table Preview 用 SELECT |

## ライセンス

Apache-2.0
