# Demo loader（業種共通）

Ossie セマンティックモデルと `demo/<domain>/output/` の生成物を、Trino Iceberg / PuppyGraph / OpenSearch に冪等投入する。

## CLI

```bash
PYTHONPATH=. python -m demo.loader \
  --domain-dir demo/mfg_quality \
  --target all \
  [--recreate] [--dry-run] \
  [--iceberg-method a|b] \
  [--allow-missing-embedding] [--skip-create] \
  [--graph-schema-out /tmp/puppygraph_schema.json]
```

投入前に `python -m solomon.semantic validate --root <domain>/semantic` を実行（`--dry-run` 以外）。

`--target` は `iceberg` → `graph` の順に実行する（PuppyGraph は Iceberg 表を Trino 経由で読むため、表が先に要る）。

CML の Session で `.solomon/deploy.env` の値を使うときは、`bootstrap_deploy_env()` を先に呼ぶ:

```bash
PYTHONPATH=. python - <<'EOF'
from solomon.infra.deploy_env import bootstrap_deploy_env
bootstrap_deploy_env()
from demo.loader.cli import main
raise SystemExit(main(["--domain-dir", "demo/mfg_quality", "--target", "iceberg"]))
EOF
```

コマンド行で付けた env（`TRINO_USER=... python - <<'EOF'`）は deploy.env より優先される（deploy.env は未設定のキーだけを埋める）。

## Trino 認証

`TRINO_USER` と `TRINO_PASSWORD` があれば Basic 認証（workload user / password）。無ければ workload の `/tmp/jwt`（`SOLOMON_CML_JWT_PATH`）を JWT として使う。

loader だけで Basic 認証を使うときは、deploy.env には書かずコマンド行で渡す（deploy.env に書くと Solomon 本体も Basic 認証に切り替わる）。

## 環境変数（Solomon と共通 + デモ用）

| 変数 | 用途 |
|------|------|
| `TRINO_*` | Iceberg 投入（`TRINO_URL` または `TRINO_HOST`、`TRINO_USER` / `TRINO_PASSWORD`） |
| `DEMO_TRINO_INSERT_MAX_BYTES` | 方式 B の INSERT 1 文の上限 bytes（既定 262144）。前段プロキシに本文サイズ上限があるときに下げる |
| `DEMO_ICEBERG_SCHEMA_LOCATION` | `CREATE SCHEMA` の location の基点（例 `s3a://<bucket>/warehouse` → `<基点>/<schema>.db`）。未設定なら metastore の既定 |
| `DEMO_S3_PREFIX` | 方式 A の Parquet 配置先。未設定なら方式 B |
| `DEMO_HIVE_CATALOG` / `DEMO_STAGE_SCHEMA` | 方式 A のステージ（既定 `hive` / `default`） |
| `OPENSEARCH_*` | 文書インデックス |
| `OPENSEARCH_DOCS_ANALYZER` | cjk / kuromoji |
| `DEMO_EMBED_MAX_CHARS` | 埋め込み用テキスト切り詰め（既定 2000） |
| `PUPPYGRAPH_HTTP_URL` / `PUPPYGRAPH_HTTP_PORT` | スキーマ POST（既定 `http://127.0.0.1:8081`） |
| `PUPPYGRAPH_USERNAME` / `PUPPYGRAPH_PASSWORD` | PuppyGraph の Basic 認証 |
| `DEMO_PUPPYGRAPH_CATALOG` | `trino` / `hms` / `rest`。未設定なら `PUPPYGRAPH_TRINO_JDBC_URI` があれば `trino`、`HIVE_METASTORE_URI` だけなら `hms`、`ICEBERG_REST_URI` だけなら `rest`、どれも無ければ `trino` |
| `PUPPYGRAPH_TRINO_CATALOG` | PuppyGraph 側のカタログ名（既定 `solomon_trino`） |
| `PUPPYGRAPH_TRINO_JDBC_URI` | PuppyGraph から Trino への JDBC URI。未設定なら `TRINO_URL` / `TRINO_HOST` から `jdbc:trino://<host>:<port>/<Ossie の catalog>?SSL=true` を作る |
| `PUPPYGRAPH_TRINO_USER` / `PUPPYGRAPH_TRINO_PASSWORD` | PuppyGraph が Trino に接続するユーザー。未設定なら `TRINO_USER` / `TRINO_PASSWORD` |
| `ICEBERG_CATALOG`, `HIVE_METASTORE_URI`, `ICEBERG_REST_URI`, … | `hms` / `rest` 形式の schema.json の `${ENV}` 置換 |

## ドメイン側ファイル

- `semantic/models/*.yaml` — 正（ローダーは読むだけ）
- `output/tables/*.parquet`, `chunks.jsonl`, `manifest.json`
- `derived.sql` — CTAS 派生表
- `puppygraph/schema.json` — 生成物（`POST` 時に env 置換。実ホスト・資格情報は書き込まない）

## Iceberg 方式

- **B**（既定）: `CREATE TABLE` + バッチ `INSERT ... VALUES`。Trino だけで完結し、S3 への upload は不要。CDW Trino はこちら
- **A**: Parquet を `DEMO_S3_PREFIX` に upload → hive 外部テーブル → `CREATE TABLE iceberg... AS SELECT`。`DEMO_S3_PREFIX` が設定され、`SHOW CATALOGS` に hive があるときだけ自動選択

どちらも先に `CREATE SCHEMA IF NOT EXISTS <catalog>.<schema>` を実行する。

## PuppyGraph（`DEMO_PUPPYGRAPH_CATALOG=trino`）

PuppyGraph 1.x の形式（`catalog` / `node` / `edge`）で、Trino カタログ経由で Iceberg 表を読むスキーマを `POST /schema` する。データはコピーしない（zero-ETL）。

- `POST /schema` は PuppyGraph の**既存スキーマを置き換える**
- JDBC URI の catalog（`jdbc:trino://host:443/<catalog>`）は Ossie の `catalog.schema.table` の catalog と一致させる
- PuppyGraph から Trino のホストに到達できる必要がある（別ネットワークの EC2 等では Security Group / 経路を確認）
- `--dry-run` は置換前の schema を表示する（password は `***`）
- `--graph-schema-out <path>` は POST せず、置換済みの schema JSON を `<path>` に書く（権限 600）。PuppyGraph UI の Schema → Upload で投入する。資格情報を含むのでリポジトリ外（`/tmp` 等）に書き、投入後は消す

## 冪等

既存表の `COUNT(*)` が Parquet 行数と一致すればスキップ。不一致（途中で失敗した INSERT の残り等）は警告を出して DROP 後に再投入。`--recreate` で全表を DROP 後に再投入。
