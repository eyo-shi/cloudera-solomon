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

- **IDBroker URL は到達できている**（401 = トークン拒否）。Console → Environment → **Manage Access → ID Broker Mappings** でユーザー / グループを Data Access ロールにマップし **Sync** する。
- Workbench Application の **Cookie JWT** は aws-cab で拒否されやすい。Solomon は **`/tmp/jwt`**（CML データレイクアクセス用）を優先する。Session で `test -f /tmp/jwt && wc -c /tmp/jwt` を確認。
- ホスト名は `...-idbroker0...`（`idbroker` の綴りに注意）。
- Log の body に **`missing required token audience`** がある場合: Workbench Application の JWT / `/tmp/jwt` が **aws-cab 用 audience ではない**。Console で **ID Broker Mappings を Sync** し、それでも 400 のときは **S3 Data Connection** 経路か、環境管理者に **Knox token / CAB audience** の設定を確認する（Solomon 単体では長期 AK/SK は使わない）。

---

## Data Connection に S3 を出したい場合（任意）

Site Administration で **Object Store / S3** タイプがプロビジョンされていれば一覧に出ます。出ない環境では **IDBroker のみ**で運用する想定です（Solomon コード上もサポート済み）。
