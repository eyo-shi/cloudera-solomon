# 製造品質トレーサビリティ デモ（架空データ）

東邦精機（Tier1）の EPS / パワーウィンドウ品質事件を、Ossie セマンティックモデルと再現可能な合成データで再現する。

## ディレクトリ

| パス | 内容 |
|------|------|
| `semantic/models/mfg_quality.yaml` | テーブル定義の唯一の正（Ossie 本家 + SOLOMON 拡張） |
| `scenario.yaml` | 隠し事実・期待回答・生成用言い換え辞書 |
| `generator/` | データ生成 CLI |
| `output/` | 生成物（Git 除外） |
| `cache/llm/` | LLM 文書キャッシュ（Git 管理可） |

## Solomon の向け方

```bash
export SOLOMON_SEMANTIC_ROOT=demo/mfg_quality/semantic
export SOLOMON_SEMANTIC_MODELS=mfg_quality
# 投入 PR まで: Trino catalog/schema を mfg_quality に合わせる
```

## 検証

```bash
python -m solomon.semantic validate --root demo/mfg_quality/semantic
SOLOMON_SEMANTIC_ROOT=demo/mfg_quality/semantic python -m solomon.semantic show
```

## データ生成

リポジトリルートで `PYTHONPATH=.` を付ける。

```bash
PYTHONPATH=. python -m demo.mfg_quality.generator --seed 42 --out demo/mfg_quality/output --docs template
PYTHONPATH=. python -m demo.mfg_quality.generator --seed 42 --scale 0.01 --docs template --out /tmp/mfg-smoke
```

- `--docs template` … LLM なし（CI / 数分以内）
- `--docs llm` … 仕込み文書等を LLM 生成（`cache/llm` を参照）
- `--only tables` / `--only docs` … 部分生成
- 完了時 `output/manifest.json` の `checks.ok` が true であること

同じ `--seed` で 2 回生成すると Parquet ハッシュが一致する。

## デモの要点

- テーブルだけでは答えにくい問い（多段ロット系譜・言い換え文書）を Graph + Search で補完する想定。
- Ossie の `search.use_synonyms: false`（症状の言い換えは scenario の生成辞書のみ）。
- 系譜段数: EPS-A200 経路 3 段、PG-310→PWR-55 は 4 段、WH-200→EPS-A210 は 5 段（固定 3 段 JOIN では KX-1 等が漏れる）。

投入（S3 / Trino / PuppyGraph / OpenSearch）は別 PR。

デモの内容とデモデータの説明（発表者・視聴者向け）: [DEMO_GUIDE.md](DEMO_GUIDE.md)
