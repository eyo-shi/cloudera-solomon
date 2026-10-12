# S3 接続（Storage タブ・取り込み・プレビュー）

Solomon は **AWS アクセスキーを Application env に置きません**。資格情報は次のどちらかです。

## 認証の優先順

| 順 | 条件 | 動作 |
|----|------|------|
| 1 | **`SOLOMON_IDBROKER_URL` が設定されている** | ログインユーザーの **Knox JWT** → IDBroker → **STS**（推奨・CDP on AWS） |
| 2 | IDBroker **未設定** | **Data Connection** の S3（`get_base_connection()`）のみ |

**Data Connections に S3 が無い環境**では、**1 の IDBroker が必須**です。Trino を env のみにした場合と同様、S3 も **post-deploy env** で足します。

---

## 必須 env（IDBroker 経路・go01-demo 想定）

```text
SOLOMON_IDBROKER_URL=https://<Knox-gateway-base>   # クラスタの IDBroker / CAB 用ベース URL
SOLOMON_AWS_REGION=us-east-1                        # データレイクのリージョン
SOLOMON_S3_BUCKETS=eyda-buk-edf7cfcf                # Storage タブに出すバケット（カンマ区切り可）
```

- **`SOLOMON_S3_BUCKETS`**: UI が `ListObjects` するバケット名。未設定時は `demo-bucket` になり、実環境では **404 / AccessDenied** になりやすい。
- **`SOLOMON_S3_CONNECTION_NAME`**: IDBroker 利用時は **不要**（S3 Data Connection が無くてよい）。

MinIO 等のカスタム endpoint のみ:

```text
SOLOMON_S3_ENDPOINT_URL=https://...
```

---

## デモで S3 が要るか

| シナリオ | S3 |
|----------|-----|
| 事前投入済み **Trino / Neo4j / OpenSearch** だけ見せる QA | **不要**（Storage・取り込みチャットを使わない） |
| **Storage** タブで Bronze パスを見せる | **必要**（上記 env + ユーザーに S3 読取権限） |
| チャットから **取り込み** | **必要** |

---

## トラブルシュート

Solomon にログインした状態で:

```text
GET /api/files/diagnostics
```

返却例の見方:

- `idbroker_configured: true` → IDBroker 経路が有効
- `s3_connection_candidates` → Data Connection 試行結果（無くても IDBroker なら可）
- `configured_buckets` → `SOLOMON_S3_BUCKETS` の解釈結果

Storage タブで一覧が空 / 403 のとき:

1. `SOLOMON_S3_BUCKETS` が **実バケット名**か
2. `SOLOMON_IDBROKER_URL` が正しいか（Application 再起動済みか）
3. ログインユーザーに **Ranger / S3 ポリシー**でその prefix が読めるか

Application Log で **`idbroker.access_denied` / HTTP 401** のとき:

- **IDBroker URL は到達できている**（401 = トークン拒否）。Console → Environment → **Manage Access → ID Broker Mappings** でユーザー / グループを Data Access ロールにマップし **Sync** する（**IAM ロールの割当**。トークン種別の問題とは別）。
- ホスト名は `...-idbroker0...`（`idbroker` の綴りに注意）。

Log の body に **`missing required token audience`** がある場合:

- **Mappings を Sync 済みでも起こり得る**。CAB が欲しいのは Workbench Cookie や ``/tmp/jwt`` ではなく、多くの場合 **Knox delegation token**（`…/gateway/dt/knoxtoken/api/v1/token` の `access_token`）です。
- Solomon は CAB 呼び出し前に **knoxtoken API** へセッション / workload JWT（および Session では Kerberos SPNEGO が使えるとき）で交換を試みます（`SOLOMON_KNOXTOKEN_URL` で URL を上書き可）。
- **Session での切り分け**（Kerberos ログイン済み notebook）:

```bash
IDB=go01-aw-dl-md-idbroker0.go01-dem.ylcu-atmi.cloudera.site
TOKEN="$(curl -s --negotiate -u: "https://${IDB}:8444/gateway/dt/knoxtoken/api/v1/token" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")"
curl -s -H "Authorization: Bearer ${TOKEN}" \
  "https://${IDB}:8444/gateway/aws-cab/cab/api/v1/credentials" | head -c 200
```

  ここが 200 なら Mappings + CAB は正常。**Application だけ 400** のときは、Application ランタイムから knoxtoken 交換ができていない（Kerberos / JWT 経路の差）可能性が高い。

- **回避**: Project に S3 Data Connection があるなら、一時的に **`SOLOMON_IDBROKER_URL` を外して** Restart すると Data Connection 経路に切り替わる（IDBroker 設定がある間は Connection は使われない）。
- それでもダメな場合は環境管理者に **Knox aws-cab topology / CAB audience** と Workbench Application からの token 取得方法を確認する（Solomon は長期 AK/SK を env に置かない）。

---

## Data Connection に S3 を出したい場合（任意）

Site Administration で **Object Store / S3** タイプがプロビジョンされていれば一覧に出ます。出ない環境では **IDBroker のみ**で運用する想定です（Solomon コード上もサポート済み）。
