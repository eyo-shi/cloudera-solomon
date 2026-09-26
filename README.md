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
| `solomon.demo.warm` | `SOLOMON_DEMO_MODE=warm` のキャンド応答フォールバック |
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

## Deploy 後の設定手順 (Post-Deploy Configuration)

AMP Deploy 時に必須入力は **なし** (optional の `SOLOMON_LOG_LEVEL` / `SOLOMON_DEMO_MODE` のみ)。
Trino / S3 / OpenSearch は Cloudera AI Workbench の **Site Administration → Data Connections** が
single source of truth。Neo4j / LLM / CDV は Deploy 完了後に **Project → Settings → Advanced →
Environment Variables** で設定し、同画面から Application を再起動して反映する。

未設定のまま UI で該当機能を叩くと、API は HTTP 503 + JSON (`{error_code, message,
instruction}`) を返し、UI の **SetupGuide カード** が手順を表示する。

### 1. Trino / CDW への接続

- Site Administration → Data Connections で CDW / Trino connection を登録済みなら、
  `SOLOMON_TRINO_CONNECTION_NAME` にその connection 名を設定する
  (未設定でも Trino タイプの connection が 1 個なら自動採用)。
- Data Connections を使わない環境では以下 4 個を代わりに設定:
  - `SOLOMON_TRINO_HOST`
  - `SOLOMON_TRINO_PORT` (default 443)
  - `SOLOMON_TRINO_CATALOG` (default `iceberg`)
  - `SOLOMON_TRINO_SCHEMA` (default `demo`)

### 2. S3 への接続

- Site Administration → Data Connections で S3 connection を登録済みなら、
  `SOLOMON_S3_CONNECTION_NAME` を設定 (省略時は S3 タイプの最初の connection を自動採用)。
- Data Connections を使わない環境では `SOLOMON_AWS_REGION` (default `us-east-1`)。
- 認証情報は IDBroker STS 経由でユーザー単位に払い出されるため、AMP には
  AWS access key / secret は一切保持しない。

### 3. Neo4j への接続

- Workbench 上で Neo4j Launcher Application を Deploy し、Application Log から
  `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` を取得して env に設定する。
- CML neo4j-launcher の内部/外部 Bolt URI フォールバックに対応している。
- 未設定時は Graph タブ・Ingestion の Neo4j 書込・Agentic RAG の graph 検索が
  `NEO4J_NOT_CONFIGURED` で停止する。

### 4. OpenSearch / Cloudera Semantic Search への接続

Solomon 内では OpenSearch を起動しない。Data Hub で **Semantic Search for AWS** を
Provision した後、Management Console からエンドポイント URL と namespace を取得する。

- Data Connections に OpenSearch connection を登録済みなら
  `SOLOMON_OPENSEARCH_CONNECTION_NAME` を設定 (省略時は OpenSearch タイプを自動検出)。
- Data Connections を使わない環境では以下を直接指定:
  - `SOLOMON_OPENSEARCH_ENDPOINT` (または `SOLOMON_OPENSEARCH_HOST`)
  - `SOLOMON_OPENSEARCH_NAMESPACE` (default `solomon`)
  - `SOLOMON_OPENSEARCH_INDEX` (default `{namespace}-datasets`)
  - `SOLOMON_OPENSEARCH_USERNAME` / `SOLOMON_OPENSEARCH_PASSWORD` (必要な場合)

Ingestion 完了後に Ossie dataset が OpenSearch にインデックスされる。
未設定時は Search タブ・RAG の keyword/hybrid 検索が `OPENSEARCH_NOT_CONFIGURED` で停止する。

### 5. LLM プロバイダ (以下いずれか 1 つを選択)

| `SOLOMON_LLM_PROVIDER` | 必須 env | 任意 env |
|---|---|---|
| `cai` (default) | `CAI_INFERENCE_BASE_URL`, `CAI_INFERENCE_API_KEY` | `SOLOMON_LLM_ROUTER_MODEL` (default `llama-3-8b-instruct`), `SOLOMON_LLM_ANALYTICS_MODEL` (default `llama-3-70b-instruct`) |
| `anthropic` | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL`, `SOLOMON_LLM_ROUTER_MODEL` (default `claude-3-5-haiku-latest`), `SOLOMON_LLM_ANALYTICS_MODEL` (default `claude-3-5-sonnet-latest`) |
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
