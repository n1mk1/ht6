from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from praxis_api.config import Settings
from praxis_api.db import Database
from praxis_api.main import create_app


@pytest.fixture
def payload() -> dict:
    path = Path(__file__).parent / "fixtures" / "qnx_session_v3.json"
    return json.loads(path.read_text())


@pytest.fixture
def app():
    settings = Settings(
        mongodb_uri="mongodb://localhost:27017",
        mongodb_db="praxis_test",
        freesolo_mode="http",
        freesolo_model="",
        freesolo_api_key="",
    )
    # mongomock gives each test an isolated, in-memory Mongo double so the
    # suite stays hermetic without a real Atlas cluster; it has no replica
    # set, so transactions are disabled here (they're exercised for real
    # against Atlas outside the test suite).
    database = Database(
        settings.mongodb_uri,
        settings.mongodb_db,
        client_factory=lambda uri: AsyncMongoMockClient(),
        supports_transactions=False,
    )
    return create_app(settings, database)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
