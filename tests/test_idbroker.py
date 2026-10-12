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
    monkeypatch.setattr(idb, "load_workload_jwt_token", lambda: "workload-token")
    ctx = UserContext(user_name="u", groups=(), knox_jwt="cookie-jwt")
    assert idb._cab_bearer_candidates(ctx) == ["cookie-jwt", "workload-token"]
