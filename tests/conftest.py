"""Shared pytest fixtures for API tests."""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from solomon.api.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as c:
        yield c
