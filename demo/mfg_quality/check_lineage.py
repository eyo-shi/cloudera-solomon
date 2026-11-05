"""Q2（系譜トレース）の切り分け: エージェントと同じツール経路で検証済みクエリを直接実行する。

CML のセッション（Solomon と同じ Project 設定）で::

    python -m demo.mfg_quality.check_lineage

各クエリの status / 件数 / 先頭行 / エラー文を表示する。期待値と違う箇所が
データ側（Trino / PuppyGraph）の問題、すべて期待どおりならエージェントの書いたクエリの問題。
"""

from __future__ import annotations

import os
import sys
from typing import Any

UNIT_LOTS = ("U-A200-260601", "U-A200-260602", "U-A200-260603")
RESIN_LOT = "HC-2605-117"


def _show(title: str, expect: str, result: dict[str, Any]) -> bool:
    ok = result.get("status") == "ok"
    rows = result.get("rows") if "rows" in result else result.get("records")
    rows = rows or []
    count = result.get("row_count", result.get("count", len(rows)))
    print(f"\n=== {title}")
    print(f"期待: {expect}")
    print(f"status={result.get('status')} rows={count if ok else '-'}")
    if not ok:
        print(f"error: {result.get('message')}")
        for att in result.get("attempts") or []:
            print(f"  attempt: {str(att)[:400]}")
    cols = result.get("columns")
    if cols:
        print("  " + " | ".join(str(c) for c in cols))
    for row in rows[:12]:
        print(f"  {row}")
    return ok and bool(rows)


def _find(items: list[dict[str, Any]], needle: str, key: str) -> str:
    for item in items:
        if needle in str(item.get("question") or ""):
            return str(item.get(key) or "")
    return ""


def main() -> int:
    os.environ.setdefault("SOLOMON_SEMANTIC_ROOT", "demo/mfg_quality/semantic")
    from solomon.infra.deploy_env import bootstrap_deploy_env

    bootstrap_deploy_env()

    from solomon.rag.agent_tools import run_graph_query, run_sql_query
    from solomon.semantic.context import get_semantic_context
    from solomon.transport.config import get_trino_config

    ctx = get_semantic_context(force=True)
    cfg = get_trino_config()
    print(f"semantic root: {os.environ.get('SOLOMON_SEMANTIC_ROOT')}")
    print(f"trino: {'catalog=' + cfg.catalog + ' schema=' + cfg.schema if cfg else '未設定'}")

    ok: dict[str, bool] = {}
    units = ", ".join(f"'{u}'" for u in UNIT_LOTS)

    def sql(title: str, expect: str, text: str) -> None:
        if not text:
            print(f"\n=== {title}\n（セマンティックモデルにクエリがありません）")
            ok[title] = False
            return
        ok[title] = _show(title, expect, run_sql_query(None, question=title, sql=text))

    def graph(title: str, expect: str, cypher: str, params: dict[str, Any]) -> None:
        if not cypher:
            print(f"\n=== {title}\n（セマンティックモデルに例がありません）")
            ok[title] = False
            return
        ok[title] = _show(title, expect, run_graph_query(None, cypher=cypher, params=params))

    sql(
        "SQL 1 段: ユニットへの投入ロット",
        "3 行（SA-A200-2605xx-01 → U-A200-26060x）",
        "SELECT child_lot_id, parent_lot_id, qty_used FROM iceberg.mfg_quality.lot_genealogy "
        f"WHERE parent_lot_id IN ({units}) ORDER BY parent_lot_id",
    )
    sql(
        "SQL 上流（検証済みクエリ）",
        f"{RESIN_LOT} (MATERIAL) と ML-2605-117-WH200-01..03 (MOLD) の 4 行",
        _find(ctx.verified_queries, "上流トレース", "sql"),
    )
    sql(
        "SQL 下流（検証済みクエリ）",
        "EPS-A200 / EPS-A210 / PWR-55 × SX-5 4100 / CV-3 2100 / KX-1 3300 / VN-7 1900（計 11,400 台）",
        _find(ctx.verified_queries, "下流トレース", "sql"),
    )
    graph(
        "Graph 1 段: ユニットへの投入ロット",
        "SA-A200-260528-01 など 1 行以上",
        "MATCH (c:Lot)-[:CONSUMED_BY]->(u:Lot {lot_id:$unit_lot_id}) "
        "RETURN c.lot_id AS child, c.lot_type AS lot_type",
        {"unit_lot_id": UNIT_LOTS[0]},
    )
    graph(
        "Graph 上流（クエリ例）",
        f"{RESIN_LOT} を含む",
        _find(ctx.graph_examples, "上流", "cypher"),
        {"unit_lot_id": UNIT_LOTS[0]},
    )
    graph(
        "Graph 下流（クエリ例）",
        "SQL 下流と同じ製品・車種・台数",
        _find(ctx.graph_examples, "下流", "cypher"),
        {"lot_id": RESIN_LOT},
    )

    print("\n=== まとめ")
    for title, passed in ok.items():
        print(f"  {'OK ' if passed else 'NG '} {title}")
    return 0 if all(ok.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
