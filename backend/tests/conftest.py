from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from praxis_api.config import Settings
from praxis_api.main import create_app


@pytest.fixture
def payload() -> dict:
    path = Path(__file__).parent / "fixtures" / "qnx_session_v3.json"
    return json.loads(path.read_text())


@pytest.fixture
def app(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "praxis.db",
        freesolo_mode="http",
        freesolo_model="",
        freesolo_api_key="",
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client
