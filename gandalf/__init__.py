"""Gandalf — Cloudera AI Agent Studio 上の Genie 相当マルチエージェント。

サブパッケージ:
    gandalf.router      Router Crew (intent 分類 / ディスパッチ)
    gandalf.ingestion   Ingestion Crew (S3 → Iceberg 取り込み)
    gandalf.analytics   Analytics Crew (サマリー / ダッシュボード)
    gandalf.semantic    Apache Ossie YAML の読み書き / 検索
    gandalf.session     セッション、リクエスト、メモリ
    gandalf.transport   認証・HTTP・ロギングの共通層
    gandalf.tools       各種 CrewAI Tool 実装
    gandalf.api         FastAPI バックエンド
    gandalf.demo        デモ用ウォームアップ / フォールバック
"""

__version__ = "0.0.1"
