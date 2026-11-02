# デモ環境 構築・確認・リハーサル手順（業種共通）

Solomon の **Agentic RAG デモ**（CDW Trino + Iceberg、PuppyGraph、OpenSearch、LLM / 埋め込み）を、再現可能に立ち上げるための手順書です。  
デモ用コードは本リポジトリの `demo/` に置きます（`demo.loader` / `demo.validate` / `demo.checks.preflight`）。

**env の置き場**

| 環境 | ファイル |
|------|----------|
| ローカル venv | `.env`（`.env.example` をコピー） |
| CML Workbench | `.solomon/deploy.env`（`deploy/deploy.env.example` をベース） |

変更後は **Solomon Application の Restart** が必要です。

---

## 未確認事項（確認結果を記入）

リハーサル前に埋め、preflight と手動確認で更新してください。

| 項目 | 確認方法 | 結果（日付・担当） | 推奨 env |
|------|----------|-------------------|----------|
| デモスクリプトの置き場 | 本リポジトリ `demo/` | | `PYTHONPATH=.` |
| Semantic Search 外部 / 内部 | `OPENSEARCH_MODE`、CML Data Connection | | `external` + `OPENSEARCH_CONNECTION_NAME` |
| kuromoji プラグイン | `GET _cat/plugins?v` または preflight | | 有 → `OPENSEARCH_DOCS_ANALYZER=kuromoji`、無 → `cjk` |
| OpenSearch インデックス作成権限 | preflight（テスト index 作成） | | 無 → loader `--skip-create` |
| PuppyGraph Iceberg 接続 | HMS thrift / REST、UI エクスポート JSON | | `DEMO_PUPPYGRAPH_CATALOG=hms\|rest` |
| Iceberg **ビュー**を PuppyGraph が読めるか | 1 ビューで試験 | | 不可なら派生は **CTAS 実表**（`derived.sql`） |
| 埋め込み入力長上限 | preflight 長文 + ベンダー doc | | `DEMO_EMBED_MAX_CHARS`（既定 2000） |
| エージェント LLM の function calling | preflight `llm_function_calling` | | 非対応 → `SOLOMON_RAG_TOOL_MODE=json` |
| CDW Trino に **hive** カタログ | `SHOW CATALOGS` | | 有 → loader 方式 A、無 → B |
| S3 書き込み先 | `DEMO_S3_PREFIX` に Parquet upload | | `s3://…/mfg_quality/…` |

一括確認:

```bash
PYTHONPATH=. python -m demo.checks.preflight \
  --semantic-root demo/mfg_quality/semantic \
  [--no-write]
```

---

## a. 事前確認チェックリスト

### Trino（CDW + Iceberg）

| 確認 | コマンド / 手段 | OK なら | NG なら |
|------|----------------|---------|---------|
| 接続 | preflight / Trino CLI | 次へ | `TRINO_URL`・認証・Ranger |
| カタログ | `SHOW CATALOGS` | hive あり → [loader 方式 A](../loader/README.md) | hive 無し → 方式 B または `--iceberg-method b` |
| スキーマ | `SHOW SCHEMAS FROM iceberg` | 対象 schema あり | `CREATE SCHEMA iceberg.<schema>` 権限を管理者に依頼 |
| 表 | 投入後 `SELECT count(*) FROM iceberg.<schema>.lot_genealogy` | 件数 ≈ manifest | `demo.loader` 再実行 / S3 パス |
| S3 | `DEMO_S3_PREFIX` へ Put | loader upload OK | IAM / IDBroker / バケットポリシー |

**デモでは `TRINO_MODE=external` 必須**（internal DuckDB は Iceberg ではなく PuppyGraph とデータを共有できない）。

### PuppyGraph

| 確認 | 手段 | OK | NG |
|------|------|----|----|
| バージョン | イメージ tag（例 1.15） | 手順どおり schema POST | ドキュメント / UI エクスポートで JSON 調整 |
| Iceberg | HMS `thrift://…` または REST URI | `DEMO_PUPPYGRAPH_CATALOG` 設定 | env プレースホルダ `${HIVE_METASTORE_URI}` 等 |
| S3 認証 | PuppyGraph 側設定 | 頂点件数 > 0 | カタログ接続ログ |
| ビュー | 試験 1 本 | 読める | **ビューは使わず CTAS** |
| HTTP 8081 | preflight `puppygraph_http` | schema POST 可 | `PUPPYGRAPH_HTTP_URL` |
| Bolt 7687 | preflight / `PUPPYGRAPH_URI` | Graph タブ・validate cluster | URI / 認証 |

internal: CML の `1_start-puppygraph` Application。external: `PUPPYGRAPH_MODE=external` + URI。

### OpenSearch

| 確認 | 手段 | OK | NG |
|------|------|----|----|
| 到達 | `GET /` | バージョン表示 | `OPENSEARCH_ENDPOINT` / Connection |
| 2.9 未満 | バージョン番号 | k-NN filter フォールバック想定 | 件数・スコアを validate で確認 |
| kuromoji | `_cat/plugins` | analyzer 推奨を preflight 表示 | `cjk` |
| 作成権限 | preflight テスト index | pass | Ranger 依頼 / `--skip-create` |
| 文書 index | loader search 後 `_count` | chunks 件数一致 | `OPENSEARCH_DOCS_INDEX` |

### 埋め込み

| 確認 | 手段 | OK | NG |
|------|------|----|----|
| モデル | `SOLOMON_LLM_EMBEDDING_MODEL=bge-m3` | preflight embedding pass | CAI / API キー |
| 次元 | ベクトル長 | `OPENSEARCH_EMBEDDING_DIM=1024` | mapping 再作成 |
| 長文 | `DEMO_EMBED_MAX_CHARS` | 切り詰め後も embed OK | 上限を下げる |

### LLM（エージェント）

| 確認 | 手段 | OK | NG |
|------|------|----|----|
| function calling | preflight | `SOLOMON_RAG_TOOL_MODE=native` 可 | **`json`** |
| 速度 | agent validate 1 run | 1 手 ≲ 10s 目安 | モデル / `max_steps` 見直し |
| 503 Setup | UI Setup Guide | provider 設定 | `SOLOMON_LLM_*` / `CAI_INFERENCE_*` |

---

## b. 業種（Ossie モデル）の切替

**再起動だけで切り替わる 3 点:**

1. `SOLOMON_SEMANTIC_ROOT=demo/<domain>/semantic`
2. `TRINO_SCHEMA=<iceberg の schema 名>`
3. `OPENSEARCH_DOCS_INDEX=<文書インデックス名>`

確認:

```bash
PYTHONPATH=. python -m solomon.semantic validate --root demo/<domain>/semantic
PYTHONPATH=. python -m solomon.semantic show --root demo/<domain>/semantic
```

製造品質の env 雛形: [`mfg_quality/env/demo.env.example`](mfg_quality/env/demo.env.example)

**新業種を足すときに用意するもの**

| 成果物 | 説明 |
|--------|------|
| `demo/<domain>/semantic/models/*.yaml` | Ossie + SOLOMON 拡張（graph / document_index / examples） |
| `demo/<domain>/scenario.yaml` | 質問・正解・search_checks |
| `demo/<domain>/generator/` または ETL | Parquet / chunks |
| `demo/<domain>/derived.sql` | CTAS 派生表 |
| `demo/<domain>/checks.py` | validate local/cluster プラグイン（任意） |

---

## c. 環境構築（順序）

1. **Trino** — `TRINO_MODE=external`、catalog `iceberg`、schema（例 `mfg_quality`）
2. **Iceberg スキーマ** — 権限があれば `CREATE SCHEMA`、なければ管理者依頼（loader README）
3. **PuppyGraph** — internal launcher または external URI；Iceberg カタログを Solomon と同じ HMS/REST に
4. **OpenSearch** — external Connection または internal launcher
5. **LLM / 埋め込み** — CAI Inference 等、`SOLOMON_LLM_EMBEDDING_MODEL=bge-m3`
6. **preflight** — 上記表の「未確認」を埋める

---

## d. データ準備

### 1. 生成（製造品質例）

```bash
PYTHONPATH=. python -m demo.mfg_quality.generator --seed 42 --scale 1.0 --docs template
```

出力: `demo/mfg_quality/output/tables/*.parquet`, `chunks.jsonl`, `manifest.json`

### 2. 投入

```bash
# TRINO_* / DEMO_S3_PREFIX / PUPPYGRAPH_* / OPENSEARCH_* を設定
PYTHONPATH=. python -m demo.loader \
  --domain-dir demo/mfg_quality \
  --target all
```

2 回目はスキップ中心（冪等）。詳細: [`loader/README.md`](loader/README.md)

### 3. 検証

```bash
PYTHONPATH=. python -m demo.validate --domain-dir demo/mfg_quality --level semantic
PYTHONPATH=. python -m demo.validate --domain-dir demo/mfg_quality --level local
# 投入後
PYTHONPATH=. python -m demo.validate --domain-dir demo/mfg_quality --level cluster
PYTHONPATH=. python -m demo.validate --domain-dir demo/mfg_quality --level agent --runs 1 --configs all
```

採点・レポート: [`validate/README.md`](validate/README.md)

---

## e. Solomon 起動と画面確認

```bash
# env 読込後
uvicorn solomon.api.main:app --reload   # または CML Application
```

| 確認 | 期待 |
|------|------|
| Tables タブ | `TRINO_SCHEMA` 配下の全表 |
| Graph タブ | Ossie 頂点ラベルが表示 |
| Search タブ | `OPENSEARCH_SEARCH_SCOPE=both` で文書ヒット |
| `GET /api/semantic/context` | `warnings` が空に近い |
| `GET /api/graph/meta` | ラベル一覧 |
| `GET /api/search/diagnostics` | docs index 接続 OK |

---

## f. リハーサル手順

1. **validate** — `semantic` → `local` → `cluster` → `agent --runs 5`（本番前）
2. **4 構成で質問**（UI または validate agent）  
   - `table` / `table_graph` / `table_search` / `all`  
   - scenario Q1〜Q7（Ossie `ai_context.examples` と一致）
3. **比較素材を用意**  
   - **段数固定 3 段 SQL** — KX-1 経路が漏れる誤答例（scenario `genealogy_hops` 参照）  
   - **keyword のみ「異音」** — H2（QR-2024-0815）が top に来ない画面（search_checks）
4. **失敗時の切り戻し**  
   - `SOLOMON_RAG_ENGINE=heuristic`  
   - `SOLOMON_DOC_SEARCH_EXPANSION=off`  
   - `SOLOMON_RAG_TOOL_MODE=json`  
   - Router のみ確認: `SOLOMON_ROUTER_KNOWLEDGE_THRESHOLD` 調整

---

## g. トラブルシュート

| 症状 | 確認 |
|------|------|
| `GRAPH_NOT_CONFIGURED` | `PUPPYGRAPH_URI`、Bolt 7687、preflight |
| `OPENSEARCH_NOT_CONFIGURED` | `OPENSEARCH_MODE` / ENDPOINT / Connection |
| `OPENSEARCH_DOCS_INDEX_MISSING` | loader `--target search` / `OPENSEARCH_DOCS_INDEX` |
| LLM 503 / Setup Guide | `/api/setup/llm`、`SOLOMON_LLM_PROVIDER`、API キー |
| 表が空 | Trino schema・Ranger SELECT |
| グラフ 0 件 | PuppyGraph schema POST、Iceberg 表データ |
| 検索 0 件 | インデックス名・analyzer・embedding 次元 |

**診断 API**

- `GET /api/search/diagnostics` — OpenSearch / docs index
- `GET /api/graph/meta` — グラフメタ
- `GET /api/semantic/context` — Ossie ソースカタログと警告

---

## 関連ドキュメント

- [loader/README.md](loader/README.md) — Iceberg / PuppyGraph / OpenSearch 投入
- [validate/README.md](validate/README.md) — 4 レベル検証
- [mfg_quality/README.md](mfg_quality/README.md) — シナリオ・生成器
- リポジトリ README — Solomon 全体の env 一覧
