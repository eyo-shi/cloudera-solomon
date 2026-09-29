"""Trino HTTP probe header requirements."""

from __future__ import annotations

import urllib.error
from unittest.mock import MagicMock, patch

from solomon.trino.http_probe import probe_trino_info


def test_probe_sends_accept_json_header() -> None:
    with patch("solomon.trino.http_probe.urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = MagicMock(status=200)
        ok, err = probe_trino_info("http://trino:8080")
    assert ok is True
    assert err is None
    request = urlopen.call_args.args[0]
    assert request.get_header("Accept") == "application/json"


def test_probe_reports_http_error() -> None:
    with patch("solomon.trino.http_probe.urllib.request.urlopen") as urlopen:
        urlopen.side_effect = urllib.error.HTTPError(
            "http://trino:8080/v1/info",
            406,
            "Not Acceptable",
            hdrs=None,
            fp=None,
        )
        ok, err = probe_trino_info("http://trino:8080")
    assert ok is False
    assert "406" in (err or "")
