"""``python -m solomon.semantic validate|normalize|show``"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from solomon.semantic.context import get_semantic_context
from solomon.semantic.models import parse_models_from_yaml
from solomon.semantic.solomon_extension import (
    KNOWN_TOP_LEVEL_KEYS,
    normalize_extension_data,
    parse_solomon_extension,
)
from solomon.semantic.store import load_models, semantic_root


def _load_paths(root: Path) -> list[Path]:
    models_dir = root / "models"
    if not models_dir.is_dir():
        return []
    return sorted(list(models_dir.glob("*.yaml")) + list(models_dir.glob("*.yml")))


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser() if args.root else semantic_root()
    errors: list[str] = []
    warnings: list[str] = []
    names_seen: set[str] = set()
    for path in _load_paths(root):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            models = parse_models_from_yaml(raw)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: parse failed: {exc}")
            continue
        for model in models:
            if model.name in names_seen:
                errors.append(f"duplicate model name: {model.name}")
            names_seen.add(model.name)
            ds_names: set[str] = set()
            for ds in model.datasets:
                if ds.name in ds_names:
                    errors.append(f"{model.name}: duplicate dataset {ds.name}")
                ds_names.add(ds.name)
            for rel in model.relationships or []:
                if rel.from_ not in ds_names:
                    errors.append(
                        f"{model.name}: relationship {rel.name!r} from "
                        f"{rel.from_!r} — unknown dataset"
                    )
                if rel.to not in ds_names:
                    errors.append(
                        f"{model.name}: relationship {rel.name!r} to "
                        f"{rel.to!r} — unknown dataset"
                    )
            for ext in model.custom_extensions:
                if ext.vendor_name.upper() == "SOLOMON":
                    try:
                        parsed = parse_solomon_extension(ext.data)
                        for key in parsed:
                            if key not in KNOWN_TOP_LEVEL_KEYS:
                                warnings.append(f"{path}: unknown SOLOMON key {key}")
                        if args.strict and not isinstance(ext.data, str):
                            warnings.append(
                                f"{path}: SOLOMON extension data should be JSON string "
                                "(run normalize)"
                            )
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{path}: SOLOMON extension invalid: {exc}")
    if args.schema:
        _logger_schema_optional(args.schema, warnings)
    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    return 1 if errors else 0


def _logger_schema_optional(schema_path: str, warnings: list[str]) -> None:
    path = Path(schema_path)
    if not path.is_file():
        warnings.append(f"schema file not found: {schema_path}")
        return
    warnings.append(f"external schema present (manual check): {schema_path}")


def cmd_normalize(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser() if args.root else semantic_root()
    changed = 0
    for path in _load_paths(root):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        updated = False

        def fix_extensions(obj: dict) -> None:
            nonlocal updated
            exts = obj.get("custom_extensions")
            if not isinstance(exts, list):
                return
            for ext in exts:
                if not isinstance(ext, dict):
                    continue
                if str(ext.get("vendor_name", "")).upper() != "SOLOMON":
                    continue
                if isinstance(ext.get("data"), dict):
                    ext["data"] = normalize_extension_data(ext["data"])
                    updated = True

        fix_extensions(raw)
        if "semantic_model" in raw:
            items = raw["semantic_model"]
            if isinstance(items, dict):
                items = [items]
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        fix_extensions(item)
        else:
            fix_extensions(raw)
        if updated and not args.dry_run:
            path.write_text(
                yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            changed += 1
    print(f"normalized files: {changed}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    if args.root:
        import os

        os.environ["SOLOMON_SEMANTIC_ROOT"] = str(Path(args.root).expanduser())
    ctx = get_semantic_context(force=True)
    summary = {
        "models": [m.name for m in ctx.models],
        "datasets": len(ctx.datasets),
        "glossary_terms": len(ctx.glossary),
        "graph_definitions": len(ctx.graph_definitions),
        "document_indexes": len(ctx.document_indexes),
        "example_questions": ctx.example_questions[:10],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m solomon.semantic")
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate", help="Validate semantic models")
    p_val.add_argument("--root", default=None)
    p_val.add_argument("--schema", default=None, help="Optional ossie-schema.json path")
    p_val.add_argument(
        "--strict",
        action="store_true",
        help="Warn when SOLOMON extension data is not a JSON string",
    )
    p_val.set_defaults(func=cmd_validate, strict=False)

    p_norm = sub.add_parser("normalize", help="Normalize SOLOMON extension data to JSON strings")
    p_norm.add_argument("--root", default=None)
    p_norm.add_argument("--dry-run", action="store_true")
    p_norm.set_defaults(func=cmd_normalize)

    p_show = sub.add_parser("show", help="Show semantic context summary")
    p_show.add_argument("--root", default=None)
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    load_models(force=True)
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
