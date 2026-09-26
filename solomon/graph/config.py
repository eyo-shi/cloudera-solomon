"""Neo4j connection settings loaded from CML project environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from solomon.graph.neo4j_connect import validate_neo4j_uri_for_ingest

DEFAULT_NEO4J_USERNAME = "neo4j"
DEFAULT_NEO4J_PASSWORD = "Neo4jPass1234"
OPTIONAL_UNSET_VALUE = "-"

_BROWSER_HOST_MARKERS = (".cloudera.site",)
_PLACEHOLDER_MARKERS = ("replace_from_application_log", "replace_from_neo4j")


def _env(name: str, default: str | None = None) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return default
    text = raw.strip()
    if not text or text == OPTIONAL_UNSET_VALUE:
        return default
    if "://" not in text and name == "NEO4J_URI":
        text = f"bolt://{text}"
    return text


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    username: str
    password: str

    @classmethod
    def from_env(cls) -> Neo4jConfig | None:
        uri = _env("NEO4J_URI")
        if not uri:
            return None
        return cls(
            uri=uri,
            username=_env("NEO4J_USERNAME", DEFAULT_NEO4J_USERNAME) or DEFAULT_NEO4J_USERNAME,
            password=_env("NEO4J_PASSWORD", DEFAULT_NEO4J_PASSWORD) or DEFAULT_NEO4J_PASSWORD,
        )

    def validate_for_ingest(self) -> None:
        validate_neo4j_uri_for_ingest(self.uri)
        password = self.password.strip()
        if not password:
            raise ValueError(
                "NEO4J_PASSWORD is empty. Set it in Project Settings > Advanced > "
                "Environment Variables (built-in default: Neo4jPass1234)."
            )
        if password == "REPLACE_FROM_NEO4J_LAUNCHER":
            raise ValueError(
                "NEO4J_PASSWORD is still the old placeholder. Update it in "
                "Project Settings > Advanced > Environment Variables."
            )


def get_neo4j_config() -> Neo4jConfig | None:
    """Return Neo4j settings when NEO4J_URI is configured, else None."""
    return Neo4jConfig.from_env()
