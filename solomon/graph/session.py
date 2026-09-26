"""Shared Neo4j read session helper (reuse existing config / URI fallback)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from solomon.graph.config import get_neo4j_config
from solomon.graph.neo4j_connect import iter_neo4j_connection_uris
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

T = TypeVar("T")


class Neo4jSessionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def with_read_session(fn: Callable[[Any], T]) -> T:
    """Neo4j driver/session を開き fn(session) を実行。接続 URI は既存 fallback を利用。"""
    config = get_neo4j_config()
    if config is None:
        raise Neo4jSessionError("NEO4J_NOT_CONFIGURED", "NEO4J_URI is not configured.")

    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise Neo4jSessionError(
            "NEO4J_CONNECT_FAILED", "neo4j driver is not installed."
        ) from exc

    last_error: Exception | None = None
    for uri in iter_neo4j_connection_uris(config.uri):
        driver = GraphDatabase.driver(uri, auth=(config.username, config.password))
        try:
            driver.verify_connectivity()
            with driver.session() as session:
                return fn(session)
        except Neo4jSessionError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            _logger.debug("neo4j_session.failed", uri=uri, error=str(exc))
        finally:
            driver.close()

    raise Neo4jSessionError(
        "NEO4J_CONNECT_FAILED",
        f"Neo4j session failed: {last_error}",
    )
