"""FastAPI バックエンド (UI ⇄ Crew の橋渡し)。

エントリポイント:

    ``python -m solomon.api.main``  または  ``solomon-api``

公開する主なオブジェクト:

* :func:`solomon.api.main.create_app` — FastAPI アプリのファクトリ
* :func:`solomon.api.main.main` — uvicorn 起動関数 (pyproject の script entry)

エンドポイントは全て ``/api/*`` プレフィックスに置く。SPA は ``/`` で
``solomon/api/static/`` から静的配信される (存在すれば)。
"""
