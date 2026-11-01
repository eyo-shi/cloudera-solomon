"""PuppyGraph read session (Bolt / openCypher)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from solomon.graph.bolt_driver import open_driver
from solomon.graph.config import get_graph_config
from solomon.transport.logging import get_logger

_logger = get_logger(__name__)

T = TypeVar("T")


class GraphSessionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def graph_connection_uris(primary_uri: str) -> list[str]:
    return [primary_uri]


def with_read_session(fn: Callable[[Any], T]) -> T:
    config = get_graph_config()
    if config is None:
        raise GraphSessionError(
            "GRAPH_NOT_CONFIGURED",
            "PUPPYGRAPH_URI is not configured. Set bolt://host:7687 in .solomon/deploy.env.",
        )

    errors: list[str] = []
    for uri in graph_connection_uris(config.uri):
        try:
            driver = open_driver(uri, username=config.username, password=config.password)
        except ImportError as exc:
            raise GraphSessionError("GRAPH_CONNECT_FAILED", str(exc)) from exc
        try:
            driver.verify_connectivity()
            with driver.session() as session:
                return fn(session)
        except GraphSessionError:
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(f"  {uri}: {exc}")
            _logger.debug("graph_session.failed", uri=uri, error=str(exc))
        finally:
            driver.close()

    detail = "\n".join(errors) if errors else "(no detail)"
    raise GraphSessionError(
        "GRAPH_CONNECT_FAILED",
        f"Could not connect to PuppyGraph at {config.uri}.\n{detail}",
    )
