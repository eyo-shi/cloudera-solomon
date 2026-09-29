"""Deploy-time internal / external mode for co-located services."""

from __future__ import annotations

import os

_INTERNAL_ALIASES = frozenset({"internal", "cml", "demo", "launcher", "embedded"})
_EXTERNAL_ALIASES = frozenset({"external", "datahub"})


def deployment_mode(env_name: str, *, default: str = "internal") -> str:
    """Return ``internal`` or ``external`` for the given env var."""
    raw = (os.environ.get(env_name) or default).strip().lower()
    if raw in _EXTERNAL_ALIASES:
        return "external"
    if raw in _INTERNAL_ALIASES or not raw:
        return "internal"
    return "internal"


def is_internal_mode(env_name: str, *, default: str = "internal") -> bool:
    return deployment_mode(env_name, default=default) == "internal"


def is_external_mode(env_name: str, *, default: str = "internal") -> bool:
    return not is_internal_mode(env_name, default=default)
