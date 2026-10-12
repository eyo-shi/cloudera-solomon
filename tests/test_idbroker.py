"""IDBroker CAB token / response parsing."""

from __future__ import annotations

from solomon.tools import _idbroker as idb
from solomon.transport.user_context import UserContext


def test_credential_fields_nested() -> None:
    data = {
        "Credentials": {
            "AccessKeyId": "AKIA",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
            "Expiration": 1_700_000_000,
        }
    }
    fields = idb._credential_fields(data)
    assert fields["AccessKeyId"] == "AKIA"


def test_cab_bearer_candidates_order(monkeypatch) -> None:
    monkeypatch.setattr(idb, "fetch_knox_delegation_token", lambda _ctx: "knox-delegation")
    monkeypatch.setattr(idb, "load_workload_jwt_token", lambda: "workload-token")
    ctx = UserContext(user_name="u", groups=(), knox_jwt="cookie-jwt")
    assert idb._cab_bearer_candidates(ctx) == [
        "knox-delegation",
        "cookie-jwt",
        "workload-token",
    ]


def test_knoxtoken_url_from_idbroker() -> None:
    import os

    os.environ["SOLOMON_IDBROKER_URL"] = "https://idb.example/gateway"
    assert idb.knoxtoken_url() == "https://idb.example/gateway/dt/knoxtoken/api/v1/token"
    os.environ["SOLOMON_KNOXTOKEN_URL"] = "https://custom/token"
    assert idb.knoxtoken_url() == "https://custom/token"
    del os.environ["SOLOMON_KNOXTOKEN_URL"]
    del os.environ["SOLOMON_IDBROKER_URL"]
