"""OpenSearch deployment mode: Data Hub (production) vs CML launcher (demo)."""

from __future__ import annotations

import os

_CML_ALIASES = frozenset({"cml", "demo", "launcher", "embedded"})


def opensearch_mode() -> str:
    raw = (os.environ.get("SOLOMON_OPENSEARCH_MODE") or "datahub").strip().lower()
    return raw or "datahub"


def is_cml_opensearch_mode() -> bool:
    return opensearch_mode() in _CML_ALIASES


def is_datahub_opensearch_mode() -> bool:
    return not is_cml_opensearch_mode()
