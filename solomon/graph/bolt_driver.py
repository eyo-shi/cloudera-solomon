"""Bolt driver access for PuppyGraph (openCypher over port 7687)."""

from __future__ import annotations

from typing import Any


def open_driver(uri: str, *, username: str, password: str) -> Any:
    """Return a connected Bolt driver context (caller must close)."""
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise ImportError(
            "Bolt driver dependency is missing. Reinstall solomon with graph extras "
            "(see pyproject.toml)."
        ) from exc
    return GraphDatabase.driver(uri, auth=(username, password))
