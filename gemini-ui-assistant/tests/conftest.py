import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config, gemini_client, main  # noqa: E402


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    """Give every test default (mock-mode) settings and a clean rate limiter,
    regardless of any local .env file or environment variables."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    test_settings = config.Settings(_env_file=None)
    monkeypatch.setattr(config, "get_settings", lambda: test_settings)
    monkeypatch.setattr(main, "get_settings", lambda: test_settings)
    monkeypatch.setattr(gemini_client, "get_settings", lambda: test_settings)
    main._request_log.clear()
    return test_settings


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    return TestClient(main.app)


@pytest.fixture
def sample_context():
    return {
        "page": "dashboard",
        "page_title": "Praxis Dashboard",
        "visible_sections": [
            {
                "id": "sessions-list",
                "label": "Sessions",
                "description": "A list of recorded path-tracing sessions.",
            }
        ],
        "visible_metrics": [
            {
                "label": "Accuracy",
                "value": "82.0",
                "help_text": "How closely the traced movement followed the reference path.",
            }
        ],
        "available_actions": [
            {
                "label": "Sync from Pi",
                "description": "Pulls the most recent session from the Praxis device.",
            }
        ],
    }
