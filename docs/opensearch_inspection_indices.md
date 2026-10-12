# OpenSearch — CDE Spark 取込（Semantic Search）

**1 Bronze ファイル = 1 ドキュメント**（Iceberg 明細は別 doc にしない）。payload は **`silver_*` ファイル行と同型 JSON**（メタのみ）。

Solomon 本体の Ingestion が作る **`{namespace}-datasets`**（例: `solomon-datasets`）とは **別インデックス群**です。製造 Bronze デモは **`inspection-*`** を参照します。

---

## いつ載るか

| 条件 | 動作 |
|------|------|
| `ingest_file_state` に無い / etag 変更 | パース → Iceberg MERGE **後** index |
| 同 `object_key` + `etag` 済み | OpenSearch **更新しない** |
| opensearch-py / URL 未設定 | **静かにスキップ** |

再投入: Trino で台帳行削除 → ジョブ再 Run。

---

## インデックス名

`OPENSEARCH_INDEX_PREFIX`（デフォルト **`inspection`**）+ フォーマット:

| インデックス | Bronze |
|--------------|--------|
| **inspection-vb** | `vb_test/**/*.TXT` |
| **inspection-j5_main_id** | `j5_main_id/*.txt` |
| **inspection-kanken** | `j5_kanken/*` |
| **inspection-j5_shukken_id** | `j5_shukken_id/*.DAT` |

`_id` = `sha256(object_key + etag)`（URL 安全）。

---

## ドキュメントフィールド

| フィールド | 内容 |
|------------|------|
| `object_key` | S3 Bronze 相対パス |
| `etag` | 版識別 |
| `format` | `vb` / `j5_main_id` / `kanken` / `j5_shukken_id` |
| `trace_id` | KIBAN（VB は空） |
| `vb_machine_no` | VB 机番（J5 は空） |
| `payload` | Iceberg `silver_*`.payload と同型 |

VB で JSON **~80KB 超** → `_truncated` / `preview` / `original_chars`（全文は Iceberg）。

---

## 3 ストア分担

| | OpenSearch | Iceberg | Neo4j |
|---|------------|---------|-------|
| 粒度 | 1 ファイル = 1 doc | ファイル行 + 明細 | ファイル + KIBAN/VB 関係 |
| 用途 | キーワード / Agent RAG | SQL・デモ QA 表 | Graph traversals |

---

## Solomon から読む

CDE Spark が **書き込み**に使う設定（例: `spark.driverEnv.*`）と、Solomon Application が **読み取り**に使う env は名前が少し違いますが、**同じ Knox ゲートウェイ URL・ユーザー・prefix** です。

| CDE (`spark.driverEnv`) | Solomon (Application env) |
|-------------------------|---------------------------|
| `OPENSEARCH_URL` | `OPENSEARCH_URL` または `OPENSEARCH_ENDPOINT` |
| `OPENSEARCH_USER` | `OPENSEARCH_USER` または `OPENSEARCH_USERNAME` |
| `OPENSEARCH_PASSWORD` | `OPENSEARCH_PASSWORD` |
| `OPENSEARCH_INDEX_PREFIX=inspection` | `OPENSEARCH_INDEX_PREFIX` または `OPENSEARCH_INSPECTION_INDEX_PREFIX` |

Solomon 最小例:

```text
OPENSEARCH_MODE=external
OPENSEARCH_URL=https://go01-css-gateway.../go01-css/cdp-proxy-api/opensearch
OPENSEARCH_USER=<CDE と同じ>
OPENSEARCH_PASSWORD=<CDE と同じ>
OPENSEARCH_INSPECTION_INDEX_PREFIX=inspection
OPENSEARCH_SEARCH_SCOPE=inspection
```

Data Connection 経由でも可（`OPENSEARCH_CONNECTION_NAME`）。その場合も prefix は上記のとおり。

製造トレース QA は Trino 優先。OpenSearch は **同一 trace_id のファイル doc 件数**を脚注できる（`solomon.opensearch.inspection_indices`）。

**Search タブ**（`GET /api/search/documents?scope=inspection`）は **`inspection-*`** をキーワード検索する（空フィルタは match_all）。Solomon Ingestion 用 **`solomon-datasets`** は `scope=datasets` または `OPENSEARCH_SEARCH_SCOPE=datasets`。

---

## 確認例

```bash
curl -sk -u 'USER:PASS' "$BASE/inspection-j5_shukken_id/_count"
curl -sk -u 'USER:PASS' "$BASE/inspection-j5_shukken_id/_search" \
  -H 'Content-Type: application/json' \
  -d '{"query":{"term":{"trace_id":"26G3V05307"}},"size":5}'
```

Ranger: **`inspection-*` の read/search** が必要（PUT のみだと `_count` が 403）。

---

## デモ一言

「Bronze 取込を **フォーマット別インデックス**に載せ、ファイル単位で KIBAN・VB 机番・ヘッダメタを検索。詳細測定は **Iceberg**、つながりは **Neo4j**、キーワードは **OpenSearch**。」
