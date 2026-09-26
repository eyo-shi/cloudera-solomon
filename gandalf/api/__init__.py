"""FastAPI バックエンド (UI ⇄ Crew の橋渡し)。

エントリポイント:

    ``python -m gandalf.api.main``  または  ``gandalf-api``

公開する主なオブジェクト:

* :func:`gandalf.api.main.create_app` — FastAPI アプリのファクトリ
* :func:`gandalf.api.main.main` — uvicorn 起動関数 (pyproject の script entry)

エンドポイントは全て ``/api/*`` プレフィックスに置く。SPA は ``/`` で
``gandalf/api/static/`` から静的配信される (存在すれば)。
"""
