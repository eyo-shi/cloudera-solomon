# Iceberg Silver — `iceberg.inspection_silver`

**カタログ / スキーマ:** `iceberg.inspection_silver`（Trino: `iceberg.inspection_silver.*`）  
**物理形式:** Iceberg、Parquet（Data Lake warehouse）

Bronze（S3 `.../bronze/`）→ CDE Spark 取込。**1 Bronze ファイル = 原則 1 行**（明細表は多行）。

Solomon の製造トレース QA（チャット「26G3V… の出検…」）は、Neo4j に加え **本スキーマを Trino で参照**する（`SOLOMON_SILVER_SCHEMA=inspection_silver`、未設定時も同デフォルト）。

---

## 1. 台帳・横断

| テーブル | 役割 | 主キー（MERGE） | 保持カラム | 1 行に相当する Bronze |
|----------|------|-----------------|------------|------------------------|
| **ingest_file_state** | 取込済み管理 | `object_key` + `etag` | `format`, `ingested_at`, `trace_id`, `vb_machine_no` | 取込成功した **各ファイル 1 行** |
| **silver_trace_links** | KIBAN↔VB・ファイル錨・バッチ相関 | `object_key`, `etag`, `trace_id`, `vb_machine_no`, `link_type` | `detail`, `confidence`, `source_object_key`, `ingested_at` | ファイル錨 + 同一バッチ相関 |

---

## 2. フォーマット別「ファイル行」（`payload` = JSON 文字列）

| テーブル | Bronze ソース | `trace_id` | `payload` 主要キー |
|----------|---------------|------------|-------------------|
| **silver_vb** | `vb_test/**/*.TXT` | 通常 null | `vb_machine_no`, `judge`, `static_step_count`, … |
| **silver_j5_main_id** | `j5_main_id/*.txt` | KIBAN | `kiban`, `hinban`, `date`, `hex_line_count`, `id_field_count`, … |
| **silver_kanken** | `j5_kanken/*.txt` | KIBAN | `kiban`, `judge`, `measurement_count`, … |
| **silver_j5_shukken_id** | `j5_shukken_id/*.DAT` | KIBAN | `at_kiban`, `customer_hinban`, `passed_at`, `hex_line_count`, … |

共通列: `object_key`, `etag`, `ingested_at`, `trace_id`, `vb_machine_no`, **`payload`**

---

## 3. 明細テーブル

| テーブル | 用途（デモ QA） |
|----------|-----------------|
| **silver_id_fields** | `timing_band = 'shukken_out'` の件数 → 出検帯の展開項目 |
| **silver_kanken_fields** | `trace_id` で COUNT → 完検測定行 |
| **silver_id_hex_lines** | hex 1 アドレス行 |
| **silver_vb_steps** / **silver_vb_section_lines** | VB 明細 |

---

## 4. Bronze → Iceberg

```text
vb_test/**/*.TXT          → silver_vb + silver_vb_steps + silver_vb_section_lines
j5_main_id/*.txt          → silver_j5_main_id + silver_id_hex_lines + silver_id_fields
j5_kanken/*               → silver_kanken + silver_kanken_fields
j5_shukken_id/*.DAT       → silver_j5_shukken_id + silver_id_hex_lines + silver_id_fields
（全フォーマット）         → ingest_file_state（+ silver_trace_links）
```

---

## 5. Trino 件数確認

```sql
SELECT 'silver_j5_shukken_id' AS t, COUNT(*) FROM iceberg.inspection_silver.silver_j5_shukken_id
UNION ALL SELECT 'silver_kanken_fields', COUNT(*) FROM iceberg.inspection_silver.silver_kanken_fields
UNION ALL SELECT 'silver_id_fields', COUNT(*) FROM iceberg.inspection_silver.silver_id_fields;
```

トレース QA 用:

```sql
SELECT json_extract_scalar(payload, '$.customer_hinban') AS customer_hinban,
       json_extract_scalar(payload, '$.passed_at') AS passed_at,
       CAST(json_extract_scalar(payload, '$.hex_line_count') AS INTEGER) AS hex_lines
FROM iceberg.inspection_silver.silver_j5_shukken_id
WHERE trace_id = '26G3V05307'
ORDER BY ingested_at DESC
LIMIT 1;

SELECT COUNT(*) FROM iceberg.inspection_silver.silver_id_fields
WHERE trace_id = '26G3V05307' AND timing_band = 'shukken_out';

SELECT COUNT(*) FROM iceberg.inspection_silver.silver_kanken_fields
WHERE trace_id = '26G3V05307';
```

**合計 10 表:** 台帳 1 + 横断 1 + ファイル行 4 + 明細 4。

Neo4j: [neo4j_bronze_graph.md](./neo4j_bronze_graph.md)。OpenSearch: [opensearch_inspection_indices.md](./opensearch_inspection_indices.md)。数値 QA は **本 Iceberg スキーマ**が正本です。
