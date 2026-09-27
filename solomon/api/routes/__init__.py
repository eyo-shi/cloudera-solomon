"""FastAPI ルート定義。

ルーターは :mod:`solomon.api.main` の :func:`create_app` から include される。

  * :mod:`.health`     — ``/healthz``
  * :mod:`.catalog`    — ``/api/catalog/*`` (Trino メタ)
  * :mod:`.graph`      — ``/api/graph/*``   (Neo4j ブラウズ)
  * :mod:`.search`     — ``/api/search/*``  (Semantic Search ブラウズ)
  * :mod:`.files`      — ``/api/files/*``   (S3 ブラウズ)
  * :mod:`.query`      — ``/api/query``     (Table Preview 用 SELECT)
  * :mod:`.ossie`      — ``/api/ossie/*``   (Ossie YAML)
  * :mod:`.artifacts`  — ``/api/artifacts/*`` (ResultPane タブの成果物)
  * :mod:`.sessions`   — ``/api/sessions/*``  (会話履歴 + entity memory)
  * :mod:`.setup`      — ``/api/setup/*``  (Deploy 後の設定プローブ)
  * :mod:`.wish`       — ``/api/wish``     (SSE — Crew 実行のストリーム)
"""
