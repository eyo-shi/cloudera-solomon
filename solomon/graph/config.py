"""PuppyGraph Bolt connection settings (openCypher over Lakehouse / RDB)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from solomon.graph.puppygraph_endpoints_file import load_bolt_uris
from solomon.graph.puppygraph_mode import (
    is_external_puppygraph_mode,
    is_internal_puppygraph_mode,
)

DEFAULT_PUPPYGRAPH_USERNAME = "puppygraph"
DEFAULT_PUPPYGRAPH_PASSWORD = "puppygraph123"
OPTIONAL_UNSET_VALUE = "-"


def _env(name: str, default: str | None = None) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return default
    text = raw.strip()
    if not text or text == OPTIONAL_UNSET_VALUE:
        return default
    if "://" not in text and name in ("PUPPYGRAPH_URI", "PUPPYGRAPH_BOLT_URI"):
        text = f"bolt://{text}"
    return text


@dataclass(frozen=True)
class GraphBoltConfig:
    uri: str
    username: str
    password: str


def _bolt_config(uri: str) -> GraphBoltConfig:
    return GraphBoltConfig(
        uri=uri,
        username=_env("PUPPYGRAPH_USERNAME", DEFAULT_PUPPYGRAPH_USERNAME)
        or DEFAULT_PUPPYGRAPH_USERNAME,
        password=_env("PUPPYGRAPH_PASSWORD", DEFAULT_PUPPYGRAPH_PASSWORD)
        or DEFAULT_PUPPYGRAPH_PASSWORD,
    )


def _resolve_uri() -> str | None:
    uri = _env("PUPPYGRAPH_URI") or _env("PUPPYGRAPH_BOLT_URI")
    if uri:
        return uri
    uris = load_bolt_uris()
    return uris[0] if uris else None


def _get_internal_config() -> GraphBoltConfig | None:
    uri = _resolve_uri()
    return _bolt_config(uri) if uri else None


def _get_external_config() -> GraphBoltConfig | None:
    uri = _env("PUPPYGRAPH_URI") or _env("PUPPYGRAPH_BOLT_URI")
    return _bolt_config(uri) if uri else None


def get_graph_config() -> GraphBoltConfig | None:
    """Return PuppyGraph Bolt settings from deploy env."""
    if is_internal_puppygraph_mode():
        return _get_internal_config()
    if is_external_puppygraph_mode():
        return _get_external_config()
    return None
