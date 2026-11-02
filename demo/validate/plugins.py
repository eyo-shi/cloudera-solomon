"""Load ``demo/<domain>/checks.py`` if present."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def load_domain_plugin(domain_dir: Path) -> ModuleType | None:
    path = domain_dir / "checks.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"demo_{domain_dir.name}_checks", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def call_plugin(
    mod: ModuleType | None,
    fn_name: str,
    *args: Any,
    **kwargs: Any,
) -> list[Any]:
    if mod is None:
        return []
    fn = getattr(mod, fn_name, None)
    if fn is None:
        return []
    out = fn(*args, **kwargs)
    if out is None:
        return []
    return list(out)


__all__ = ["load_domain_plugin", "call_plugin"]
