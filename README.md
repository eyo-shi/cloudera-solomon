# Solomon

Cloudera AI Agent Studio 上で動作する自然言語データ分析マルチエージェント。ユーザーが日本語 / 英語で問い合わせるだけで **S3 → Iceberg 取り込み / Neo4j グラフDBへのノード・リレーション追加 / テーブルサマリー生成 / Cloudera Data Visualization ダッシュボード作成** を一気通貫に実行する。3 ペイン Web UI (React + Vite) + FastAPI バックエンドを Cloudera AI Workbench Application として配信する。

セマンティックレイヤは **Apache Ossie**（YAML 仕様）を採用し、`semantic/` 配下で Git 管理する。

## 構成

```
solomon/           Python パッケージ (Crew + FastAPI)
  router/       Router Crew (intent 分類 / ディスパッチ)
  ingestion/    Ingestion Crew (S3 → Iceberg → Neo4j)
  graph/        Neo4j 接続・グラフ投入
  analytics/    Analytics Crew (サマリー / ダッシュボード)
  semantic/     Ossie YAML 読み書き / 検索
  session/      セッション、リクエスト、メモリ
  transport/    Knox JWT / HTTP / ロギング共通層
  tools/        CrewAI Tool 実装
  api/          FastAPI (SSE ストリーム、静的 SPA 配信)
  demo/         デモ用ウォームアップ

solomon_ui/        React + TypeScript + Vite (3 ペイン UI)
  src/panes/
    TreePane/   左: iceberg / s3 エクスプローラ
    ResultPane/ 中央: Table / Dashboard / Summary / SQL / File のタブ
    ChatPane/   右: SSE ストリーム対応チャット

semantic/       Apache Ossie YAML の Git 管理領域
tests/          pytest
agent_studio_manifest/     Agent Studio 用 tools/agents/crews YAML (自動生成)
.project-metadata.yaml     Cloudera AI Workbench (AMP) マニフェスト
application.json           Workbench Application 起動定義
pyproject.toml
```

## 実装ステータス

MVP 実装完了。以下の全レイヤが `main` に入っている:

| モジュール | 内容 |
|---|---|
| `solomon.transport` | Knox JWT / user_context / HTTP client / structlog / `BaseSolomonTool` |
| `solomon.tools` | S3 / Trino / フォーマット判定 / Excel ヘッダー検出 (heuristic + LLM 検証) / CDV |
| `solomon.ingestion.IngestionCrew` | S3 → Iceberg → Neo4j → Ossie の 9 タスク Sequential パイプライン |
| `solomon.graph` | Neo4j 接続 (CML neo4j-launcher 対応) と Dataset / Column / SourceFile グラフ投入 |
| `solomon.analytics.AnalyticsCrew` | Summary パス (2 タスク) + Dashboard パス (4 タスク、VizPlanner + CDV) |
| `solomon.router.RouterCrew` | intent 分類 + Python レベルディスパッチ |
| `solomon.api` | FastAPI (`/api/wish` SSE / `/api/catalog` / `/api/files/preview` / `/api/query` / `/api/artifacts` / SPA mount) |
| `solomon_ui` | React + Vite 3 ペイン UI (TreePane / ResultPane 5 タブ / ChatPane SSE) |
| `solomon.demo.warm` | `SOLOMON_DEMO_MODE=warm` のキャンド応答フォールバック |
| `solomon.manifest` | Python 定義から Agent Studio manifest (`tools.yaml` / `agents.yaml` / `crews.yaml`) を自動生成 |
| `.project-metadata.yaml` | Cloudera AI Workbench (AMP) 登録用マニフェスト |

未着手 (v2 候補): TablePreview の仮想スクロール、Ossie バッジの実 YAML 判定、セッション履歴の hydrate、Analytics の Hierarchical Process 移行。

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

### Cloudera AI Workbench で配信

AMP Deploy では Step 2 が nvm + `npm ci && npm run build` を自動実行する。
手動ビルドする場合のみ:

1. `cd solomon_ui && npm ci && npm run build`
2. Workbench Application として `python -m solomon.api.main` を起動 (`CDSW_APP_PORT` を uvicorn に渡す)
3. FastAPI が `/api/*` と `/` (SPA) を配信

## Deploy 後の設定手順 (Post-Deploy Configuration)

AMP Deploy 時に必須入力は **なし** (optional の `SOLOMON_LOG_LEVEL` / `SOLOMON_DEMO_MODE` のみ)。
Trino / S3 は Cloudera AI Workbench の **Site Administration → Data Connections** が
single source of truth。LLM / CDV は Deploy 完了後に **Project → Settings → Advanced →
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

### 3. LLM プロバイダ (以下いずれか 1 つを選択)

| `SOLOMON_LLM_PROVIDER` | 必須 env | 任意 env |
|---|---|---|
| `cai` (default) | `CAI_INFERENCE_BASE_URL`, `CAI_INFERENCE_API_KEY` | `SOLOMON_LLM_ROUTER_MODEL` (default `llama-3-8b-instruct`), `SOLOMON_LLM_ANALYTICS_MODEL` (default `llama-3-70b-instruct`) |
| `anthropic` | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL`, `SOLOMON_LLM_ROUTER_MODEL` (default `claude-3-5-haiku-latest`), `SOLOMON_LLM_ANALYTICS_MODEL` (default `claude-3-5-sonnet-latest`) |
| `openai` | `OPENAI_API_KEY` | `OPENAI_BASE_URL`, `SOLOMON_LLM_ROUTER_MODEL` (default `gpt-4o-mini`), `SOLOMON_LLM_ANALYTICS_MODEL` (default `gpt-4o`) |
| `bedrock` | `AWS_REGION` (or `SOLOMON_AWS_REGION`, IAM role 前提) | `SOLOMON_LLM_ROUTER_MODEL`, `SOLOMON_LLM_ANALYTICS_MODEL` |

### 4. Cloudera Data Visualization (Deploy 後にプロジェクト内で有効化)

1. Cloudera AI Workbench の Data メニューから CDV を **Enable** する
   (プロジェクトごとに一度だけ実行が必要)
2. 有効化後に払い出された CDV endpoint URL を `SOLOMON_CDV_BASE_URL` に設定
3. Trino connection ID を CDV 側で用意している場合は `SOLOMON_CDV_TRINO_CONNECTION_ID`
   に設定 (省略可)

CDV 未設定でも取り込み・サマリーはそのまま動作する。ダッシュボード生成のみ
`CDV_NOT_CONFIGURED` エラーで停止し、ChatPane に SetupGuide カードが表示される。

### 反映方法

いずれの env も Project → Settings → Advanced → Environment Variables で追加した後、
同画面の **Application (Solomon) を Restart** することで反映される。

## ライセンス

Apache-2.0
