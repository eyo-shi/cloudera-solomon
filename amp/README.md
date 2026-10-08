# AMP セットアップスクリプト

Cloudera AI Workbench の AMP カタログから 1 クリックで Solomon を起動するための
セットアップ手順を、順番に並べたスクリプト群。`.project-metadata.yaml` の
`tasks:` から順に参照される。

| # | Script | 内容 |
|---|---|---|
| 1 | `01_install_python_deps.py` | `pip install -e . --no-deps`（依存は Solomon Edition Runtime に bake 済み） |
| 2 | `02_build_ui.py` | nvm で Node.js 20 を自動導入 → `npm ci` / `npm run build` → `solomon/api/static/` |
| 3 | `03_seed_semantic.py` | `semantic/{datasets,metrics,...}` を用意し、Git 初期化 (既存 repo は no-op) |
| 4 | `04_verify_manifest.py` | `python -m solomon.manifest --check` で Python ⇄ YAML drift を検出 |
| 5 | `05_start_application.py` | env 正規化 → `CDSW_APP_PORT` 待機 → uvicorn 起動 |

各スクリプトは失敗時に非 0 で exit し、Workbench の AMP セットアップ画面に
エラーを表示する。ローカルで手動でも `python amp/0N_*.py` として実行可能。

## カスタム Runtime (Solomon Edition)

Deploy 時間短縮のため、本番 Python 依存はカスタム Runtime イメージに事前インストールする。

| ファイル | 用途 |
|---|---|
| `requirements-runtime.txt` | Runtime に bake する pip 依存 (pyproject.toml と同期) |
| `Dockerfile.solomon-runtime` | Cloudera PBJ Workbench Python 3.12 ベースの拡張 Dockerfile |

ビルド後、Runtime Catalog に登録し `.project-metadata.yaml` の `edition: Solomon Edition`
を指定する。Deploy 時 Step 1 は `pip install -e . --no-deps` のみ。
