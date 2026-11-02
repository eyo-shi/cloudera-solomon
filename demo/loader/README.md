# Demo loader（業種共通）

Ossie セマンティックモデルと `demo/<domain>/output/` の生成物を、Trino Iceberg / PuppyGraph / OpenSearch に冪等投入する。

## CLI

```bash
PYTHONPATH=. python -m demo.loader \
  --domain-dir demo/mfg_quality \
  --target all \
  [--recreate] [--dry-run] \
  [--iceberg-method a|b] \
  [--allow-missing-embedding] [--skip-create]
```

投入前に `python -m solomon.semantic validate --root <domain>/semantic` を実行（`--dry-run` 以外）。

## 環境変数（Solomon と共通 + デモ用）

| 変数 | 用途 |
|------|------|
| `TRINO_*` | Iceberg 投入 |
| `DEMO_S3_PREFIX` | Parquet 配置先（既定 `s3://demo-data`） |
| `DEMO_HIVE_CATALOG` / `DEMO_STAGE_SCHEMA` | 方式 A のステージ |
| `OPENSEARCH_*` | 文書インデックス |
| `OPENSEARCH_DOCS_ANALYZER` | cjk / kuromoji |
| `DEMO_EMBED_MAX_CHARS` | 埋め込み用テキスト切り詰め（既定 2000） |
| `PUPPYGRAPH_HTTP_URL` / `PUPPYGRAPH_HTTP_PORT` | スキーマ POST |
| `PUPPYGRAPH_USERNAME` / `PUPPYGRAPH_PASSWORD` | Basic 認 |
| `DEMO_PUPPYGRAPH_CATALOG` | `hms` / `rest` |
| `ICEBERG_CATALOG`, `HIVE_METASTORE_URI`, `ICEBERG_REST_URI`, … | schema.json の `${ENV}` 置換 |

## ドメイン側ファイル

- `semantic/models/*.yaml` — 正（ローダーは読むだけ）
- `output/tables/*.parquet`, `chunks.jsonl`, `manifest.json`
- `derived.sql` — CTAS 派生表
- `puppygraph/schema.json` — 生成物（Git 管理、`POST` 時に env 置換）

## Iceberg 方式

- **A**: hive 外部テーブル → `CREATE TABLE iceberg... AS SELECT`（`SHOW CATALOGS` で hive があれば自動）
- **B**: DDL + バッチ `INSERT`（hive 無し / 権限制限時）

## 冪等

既存表の `COUNT(*)` が Parquet 行数と一致すればスキップ。不一致は警告。`--recreate` で DROP 後に再投入。
