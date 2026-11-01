"""Bolt connectivity probe for PuppyGraph (openCypher port 7687)."""

from __future__ import annotations


def probe_bolt(
    uri: str,
    *,
    username: str,
    password: str,
    timeout: float = 5.0,
) -> tuple[bool, str | None]:
    """Return (ok, error_message)."""
    try:
        from solomon.graph.bolt_driver import open_driver
    except ImportError as exc:
        return False, str(exc)

    driver = open_driver(uri, username=username, password=password)
    try:
        driver.verify_connectivity()
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    finally:
        driver.close()
