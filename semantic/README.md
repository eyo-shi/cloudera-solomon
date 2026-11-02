# Semantic layer (Apache Ossie)

Solomon reads **official Ossie semantic models** from this directory. Place one model per file:

```
semantic/
  models/
    my_domain.yaml
```

Configure the root with `SOLOMON_SEMANTIC_ROOT` (default: `./semantic`). Limit loaded models with `SOLOMON_SEMANTIC_MODELS=model_a,model_b`.

## Format

Use the Ossie core semantic model (single root object or legacy `semantic_model` array wrapper). Each model includes:

- `name`, `description`, `ai_context`
- `datasets[]` with `fields[]`, `metrics[]`, `source` (`catalog.schema.table` when applicable)
- `relationships[]`, model-level `metrics[]`
- `custom_extensions[]` for vendor-specific metadata

Solomon-specific hints live under `custom_extensions` with `vendor_name: SOLOMON` (graph notes, document index mapping, tool hints, verified SQL, glossary). See `solomon/semantic/solomon_extension.py`.

## CLI

```bash
SOLOMON_SEMANTIC_ROOT=./semantic python -m solomon.semantic validate
SOLOMON_SEMANTIC_ROOT=./semantic python -m solomon.semantic show
python -m solomon.semantic normalize --root ./semantic
```

## Tests

Neutral fixtures live under `tests/fixtures/semantic/`. Point `SOLOMON_SEMANTIC_ROOT` there for local verification.

Industry-specific models belong in separate demo directories (for example `demo/<domain>/semantic/models/`), not in the core Solomon package.
