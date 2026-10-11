# Neo4j — Bronze 取込グラフ（Spark `write_neo4j` / sample Cypher）

Iceberg のような明細行の正規化は **しない**。**ファイル単位 MERGE** が中心。測定値・hex・`payload` 本体は **Iceberg** / **OpenSearch** 側。

Solomon の製造トレース QA（表の数値）は **`iceberg.inspection_silver`** を優先。Neo4j は **KIBAN と SourceFile の関係**の補足用。

---

## ノード

| ラベル | 識別子 | プロパティ | 意味 |
|--------|--------|------------|------|
| **Product** | `trace_id` | `updated_at` | トレースハブ（VB のみ → `unknown`） |
| **Kiban** | `id` | （id のみ） | KIBAN / A/T 機番 |
| **VbMachine** | `id` | （id のみ） | V/B 机番 |
| **SourceFile** | `key` | `format`, `etag` | Bronze 1 ファイル |

---

## リレーション

| 関係 | 向き | 意味 |
|------|------|------|
| **INGESTED_INTO** | `SourceFile` → `Product` | ファイルがどの Product に載ったか |
| **HAS_KIBAN** | `Product` → `Kiban` | KIBAN ありファイル |
| **VB_TEST** | `VbMachine` → `Product` | VB 机番 → Product |
| **TESTED_ON_VB** | `Kiban` → `VbMachine` | 横断リンク（`link_type`, `confidence`, `detail`） |

`TESTED_ON_VB` は `batch_trace_links` で **`trace_id` と `vb_machine_no` が両方ある**行のみ。

---

## 1 ファイルあたりの MERGE

1. **Product** — `trace_id` または `unknown`（VB のみ）
2. **Kiban** — `trace_id` あり → `Product-[:HAS_KIBAN]->Kiban`
3. **VbMachine** — `vb_machine_no` あり → `VbMachine-[:VB_TEST]->Product`
4. **SourceFile** — `SourceFile-[:INGESTED_INTO]->Product`

---

## sample 119 ファイルの目安

| フォーマット | SourceFile | グラフ上の特徴 |
|--------------|------------|----------------|
| VB | ~86 | VbMachine、`Product.unknown` に集中しがち |
| j5_main_id | ~35 | Product(KIBAN) + Kiban |
| kanken | ~20 | 同上 |
| j5_shukken_id | ~20 | 同上 |

---

## 制限（デモで言及）

- **TESTED_ON_VB** が 0 件になりやすい（sample の `vb_machine_no` 付き batch リンクなし）
- VB ↔ KIBAN は Iceberg `silver_trace_links` にあっても Neo4j には未反映のことがある
- 明細数値は **Iceberg**（`silver_id_fields`, `silver_kanken_fields` 等）

---

## Cypher 例

```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(*) ORDER BY label;

MATCH (f:SourceFile) RETURN f.format, count(*) ORDER BY f.format;

MATCH (k:Kiban {id: '26G3V05307'})<-[:HAS_KIBAN]-(p:Product)<-[:INGESTED_INTO]-(f:SourceFile)
RETURN f.key, f.format;

MATCH (k:Kiban)-[r:TESTED_ON_VB]->(v:VbMachine)
RETURN k.id, v.id, r.link_type LIMIT 20;
```

---

## 3 ストアの役割

| ストア | 役割 |
|--------|------|
| **Iceberg** | 台帳・payload・明細（デモ QA の表） |
| **OpenSearch** | ファイル単位検索（[opensearch_inspection_indices.md](./opensearch_inspection_indices.md)） |
| **Neo4j** | KIBAN / VB / SourceFile **関係**（Graph タブ・ traversals） |
