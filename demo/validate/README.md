# Demo validate（リハーサル前チェック）

4 レベルでデモの Ossie・生成物・投入データ・エージェント回答を検証する。

```bash
PYTHONPATH=. python -m demo.validate \
  --domain-dir demo/mfg_quality \
  --level semantic|local|cluster|agent \
  [--runs 5] [--questions Q1,Q2] \
  [--configs table,table_graph,table_search,all] \
  [--api http://127.0.0.1:8000] \
  [--header "Authorization: Bearer …"]
```

レポート: `demo/<domain>/reports/<YYYYmmdd-HHMM>/summary.md` と `details.csv`。

## レベル

| level | 内容 |
|-------|------|
| semantic | `solomon.semantic validate`、scenario 質問 ⊆ Ossie examples、heuristic → KNOWLEDGE_RAG、Parquet 列、domain-neutral |
| local | FK（relationships）、`demo/<domain>/checks.py` |
| cluster | Trino / Bolt / OpenSearch search_checks、`checks.run_cluster` |
| agent | `/api/wish` SSE、構成 × 質問 × runs |

## エージェント採点

- 期待値: `scenario.yaml` の `expected_answers` を文字列化し、回答に含まれるか（NFKC・カンマ除去で正規化）。
- **◎**: 期待キー含有率 **≥ 80%** かつ禁止語なし  
- **○**: ≥ 50%  
- **△**: > 0%  
- **×**: 0% または forbidden 含有 / HTTP エラー

## 環境

- `DEMO_VALIDATE_HTTP_HEADERS`: JSON オブジェクト（認証ヘッダ等）
- cluster / agent は Trino・OpenSearch・Solomon API・LLM が必要（未設定時は該当チェックを skip または FAIL）

レポートには **Ossie ハッシュ**、**埋め込みモデル**、**OPENSEARCH_DOCS_ANALYZER**、**言い換え既定** を記録する。
