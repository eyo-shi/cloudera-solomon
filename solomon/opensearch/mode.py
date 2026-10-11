"""OpenSearch deployment mode (internal launcher vs external cluster)."""

from __future__ import annotations

import os

from solomon.infra.deployment_mode import deployment_mode
from solomon.infra.env_compat import env_first

_MODE_ENV = "OPENSEARCH_MODE"
_LEGACY_MODE_ENV = "SOLOMON_OPENSEARCH_MODE"


def opensearch_mode() -> str:
    raw = env_first(_MODE_ENV, _LEGACY_MODE_ENV)
    if raw is None:
        return "external"
    previous = os.environ.get(_MODE_ENV)
    os.environ[_MODE_ENV] = raw
    try:
        return deployment_mode(_MODE_ENV, default="external")
    finally:
        if previous is None:
            os.environ.pop(_MODE_ENV, None)
        else:
            os.environ[_MODE_ENV] = previous


def is_internal_opensearch_mode() -> bool:
    return opensearch_mode() == "internal"


def is_external_opensearch_mode() -> bool:
    return not is_internal_opensearch_mode()
