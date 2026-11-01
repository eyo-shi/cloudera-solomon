# Air-gap 向け AMP Deploy

Outbound なし（または限られた private registry のみ）で Solomon AMP を Deploy するためのチェックリスト。
**完全オフライン**は、接続可能なステージングで **成果物を先に作り、private registry / プロジェクトに持ち込む** 前提です。

## 接続が発生しうる箇所

| フェーズ | 何が外部へ行くか | Air-gap 対策 |
|----------|------------------|--------------|
| **Runtime ビルド**（Deploy 前・接続ゾーン） | Cloudera ベースイメージ、PyPI、NodeSource/apt | 社内 registry に mirror。Runtime イメージを **1 回 push** し Catalog 登録 |
| **AMP Step 1** pip | カスタム Runtime 未使用時のみ PyPI | **Edition: Solomon Edition** 必須 → `pip install -e . --no-deps` のみ |
| **AMP Step 2** UI | `npm ci` → npm registry。Node 無し時は **GitHub raw (nvm)** | Runtime に **Node 20 同梱**（Solomon Edition 既定）。`SOLOMON_SKIP_UI_BUILD=true` で **事前ビルド static を使用** |
| **internal launcher** | K8s が **Docker イメージ pull** | 下表の `*_IMAGE` を **社内 registry** に向ける |
| **Solomon 実行時** | LLM / Trino / OpenSearch / S3 / CDV（post-deploy） | Deploy とは別。社内エンドポイントのみ設定 |

OpenSearch / Trino / PuppyGraph の **サーバー本体**は ML Runtime の pip には入らない。internal 時は **別コンテナイメージ**（`*_IMAGE` / `PUPPYGRAPH_IMAGE`）の pull が必要。

## 必須: Solomon Edition カスタム Runtime

1. 接続ゾーンで `amp/Dockerfile.solomon-runtime` + `amp/requirements-runtime.txt` からビルド
2. イメージを **Air-gap クラスタが pull できる registry** へ push
3. **Runtime Catalog** に登録（`edition: Solomon Edition`）
4. AMP / プロジェクトでその Edition を選択

internal 時は **`PUPPYGRAPH_IMAGE`** で mirror した `puppygraph/puppygraph` を指定する。

## AMP Step 2（UI）をオフラインで通す

`solomon/api/static/` は通常 `.gitignore` 対象。Air-gap では **Deploy 前にプロジェクト内に置く**。

**接続ゾーンで 1 回:**

```bash
cd solomon_ui && npm ci && npm run build
# 出力: solomon/api/static/
```

**Air-gap プロジェクトへ** `solomon/api/static/` を同梱（アーカイブ import 等）。

**Workbench Project → Settings → Environment Variables**（AMP 実行前）:

```bash
SOLOMON_SKIP_UI_BUILD=true
```

Solomon Edition に Node が入っていても、skip 時は **npm に触れない**。

## internal launcher 用イメージ mirror

launcher Pod 用 env（Project Settings または Application env）。`registry.example/solomon/...` は貴社 mirror に置換。

| 変数 | 既定（公网） | 用途 |
|------|--------------|------|
| `OPENSEARCH_IMAGE` | `opensearchproject/opensearch:2.11.1` | OpenSearch 本体 |
| `OPENSEARCH_DASHBOARDS_IMAGE` | `opensearchproject/opensearch-dashboards:2.11.1` | Dashboards |
| `TRINO_IMAGE` | `trinodb/trino:476` | Trino coordinator |
| `DUCKDB_INIT_IMAGE` | `busybox:1.36` | warehouse init |
| `PUPPYGRAPH_IMAGE` | `puppygraph/puppygraph:1.15.0` | PuppyGraph 本体 |

## Deploy モードの現実的な組み合わせ

| 目的 | 推奨 |
|------|------|
| Deploy 中の outbound 最小 | Solomon Edition + `SOLOMON_SKIP_UI_BUILD=true` + static 同梱 |
| internal も Air-gap | 上記 + 全 `*_IMAGE` を private registry + **事前 pull**（イメージ preload ポリシー） |
| Graph のみ internal | `PUPPYGRAPH_MODE=internal` + `PUPPYGRAPH_IMAGE` mirror |
| 検索・SQL は社内既存 | `OPENSEARCH_MODE=external` / `TRINO_MODE=external` + post-deploy のみ |

## Runtime ビルドを Air-gap クラスタ内で行う場合

- Cloudera **ベース ML Runtime** イメージを社内 mirror 必須
- Dockerfile 内 `apt` / `curl`（NodeSource）も **リポジトリ mirror** または **オフライン deb レイヤ** が必要
- 現実的には **接続ゾーンで Runtime を完成させ、イメージだけ持ち込む** 方が一般的

## 検証

Deploy 成功後:

- `GET /api/graph/meta` / Tables / Search が post-deploy 設定どおり応答するか
- internal launcher の `/launcher` status が `running`
- 初回 Pod 起動で **ImagePullBackOff** が出ないか（mirror 漏れのサイン）
