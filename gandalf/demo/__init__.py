"""デモ用ウォームアップ / フォールバック (``GANDALF_DEMO_MODE=warm`` で差替)。

デモ本番中に LLM / CDV / Trino の初回応答遅延やネットワーク瞬断でシナリオが
崩れないよう、canned な (事前ウォーミング済みの) 応答を返せるようにする。

公開 API は :mod:`gandalf.demo.warm` に集約:

* :func:`~gandalf.demo.warm.is_warm_mode`     — ``GANDALF_DEMO_MODE=warm`` かどうか
* :func:`~gandalf.demo.warm.warm_table`       — canned な Iceberg テーブル情報
* :func:`~gandalf.demo.warm.warm_summary`     — canned な Markdown サマリー
* :func:`~gandalf.demo.warm.warm_dashboard`   — canned な CDV ダッシュボード情報
* :func:`~gandalf.demo.warm.list_warm_tables` — canned に登録済みのテーブル FQ
* :func:`~gandalf.demo.warm.has_warm_asset`   — 指定 FQ が canned セットにあるか
"""
from gandalf.demo.warm import (
    has_warm_asset,
    is_warm_mode,
    list_warm_tables,
    warm_dashboard,
    warm_summary,
    warm_table,
)

__all__ = [
    "is_warm_mode",
    "warm_table",
    "warm_summary",
    "warm_dashboard",
    "list_warm_tables",
    "has_warm_asset",
]
