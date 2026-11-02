-- 派生表（PuppyGraph / ローカル検証用）。Iceberg CTAS。
-- lots: 材料・成形・サブ組立・ユニットを統合（Lot 頂点用）

CREATE TABLE IF NOT EXISTS iceberg.mfg_quality.lots WITH (format = 'PARQUET') AS
SELECT lot_id, 'MATERIAL' AS lot_type, part_no, CAST(NULL AS varchar) AS plant,
       receipt_date AS prod_date, CAST(NULL AS varchar) AS equipment_id, CAST(NULL AS integer) AS qty
FROM iceberg.mfg_quality.material_lots
UNION ALL
SELECT lot_id, lot_type, part_no, plant, prod_date, equipment_id, qty
FROM (
  SELECT u.lot_id, 'UNIT' AS lot_type, u.part_no, u.plant, u.prod_date, CAST(NULL AS varchar) AS equipment_id, u.qty
  FROM iceberg.mfg_quality.unit_lots u
) t
WHERE NOT EXISTS (SELECT 1 FROM iceberg.mfg_quality.lots x WHERE x.lot_id = t.lot_id);
