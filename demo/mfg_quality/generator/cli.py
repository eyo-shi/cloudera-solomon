"""CLI: python -m demo.mfg_quality.generator"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from demo.mfg_quality.generator.checks import run_checks
from demo.mfg_quality.generator.documents import generate_documents
from demo.mfg_quality.generator.inject import inject_scenario
from demo.mfg_quality.generator.schema_loader import load_dataset_schemas
from demo.mfg_quality.generator.simulate import fill_background

DEMO_ROOT = Path(__file__).resolve().parents[1]


def _write_parquet(frames: dict, out_dir: Path) -> None:
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, df in frames.items():
        if name.startswith("_") or df is None or df.empty:
            continue
        path = tables_dir / f"{name}.parquet"
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, path)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return hashes


def _df_to_parquet_schema(df, cols):
    import pandas as pd

    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def run(args: argparse.Namespace) -> int:
    demo_root = DEMO_ROOT
    semantic_root = demo_root / "semantic"
    scenario = yaml.safe_load((demo_root / "scenario.yaml").read_text(encoding="utf-8"))
    seed = args.seed if args.seed is not None else scenario.get("seed_default", 42)
    rng = random.Random(seed)
    scale = args.scale
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    schemas = load_dataset_schemas(semantic_root)
    frames = inject_scenario(scenario, schemas)

    if args.only in (None, "tables"):
        frames = fill_background(frames, scenario, scale=scale, rng=rng)

    if args.only in (None, "docs"):
        doc_index, ml, me, mp, docs_jsonl, chunks_jsonl = generate_documents(
            scenario,
            scale=scale,
            mode=args.docs,
            rng=rng,
            cache_dir=demo_root / "cache" / "llm",
        )
        frames["doc_index"] = doc_index
        frames["doc_mentions_lot"] = ml
        frames["doc_mentions_equipment"] = me
        frames["doc_mentions_part"] = mp
        with (out_dir / "docs.jsonl").open("w", encoding="utf-8") as fh:
            for row in docs_jsonl:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        with (out_dir / "chunks.jsonl").open("w", encoding="utf-8") as fh:
            for row in chunks_jsonl:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    # Align columns to Ossie
    for name, cols in schemas.items():
        if name not in frames or name.startswith("_"):
            continue
        col_names = [c["name"] for c in cols]
        import pandas as pd

        df = frames[name]
        for cn in col_names:
            if cn not in df.columns:
                df[cn] = pd.NA
        frames[name] = df[col_names] if len(df) else pd.DataFrame(columns=col_names)

    check = run_checks(frames, scenario)
    table_hashes = _write_parquet(frames, out_dir)

    manifest = {
        "seed": seed,
        "scale": scale,
        "docs_mode": args.docs,
        "checks": check,
        "table_hashes": table_hashes,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not check["ok"]:
        print("Self-check FAILED:")
        for c in check["checks"]:
            if not c["ok"]:
                print(" ", c)
        return 1
    print(f"OK seed={seed} scale={scale} -> {out_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m demo.mfg_quality.generator")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--out", default=str(DEMO_ROOT / "output"))
    parser.add_argument("--docs", choices=["template", "llm"], default="template")
    parser.add_argument("--only", choices=["tables", "docs"], default=None)
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
