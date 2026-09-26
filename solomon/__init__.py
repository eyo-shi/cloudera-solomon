"""Solomon — Cloudera AI Agent Studio 上の Genie 相当マルチエージェント。

サブパッケージ:
    solomon.router      Router Crew (intent 分類 / ディスパッチ)
    solomon.ingestion   Ingestion Crew (S3 → Iceberg 取り込み)
    solomon.analytics   Analytics Crew (サマリー / ダッシュボード)
    solomon.semantic    Apache Ossie YAML の読み書き / 検索
    solomon.session     セッション、リクエスト、メモリ
    solomon.transport   認証・HTTP・ロギングの共通層
    solomon.tools       各種 CrewAI Tool 実装
    solomon.api         FastAPI バックエンド
    solomon.demo        デモ用ウォームアップ / フォールバック
"""

__version__ = "0.0.1"
