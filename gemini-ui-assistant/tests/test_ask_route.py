"""Tests for POST /assistant-api/ask."""

from server import main
from server.gemini_client import AssistantUpstreamError
from server.schemas import MAX_QUESTION_CHARS


def test_health_reports_mock_mode(client):
    res = client.get("/assistant-api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["mock_mode"] is True


def test_ask_returns_mock_answer(client, sample_context):
    res = client.post(
        "/assistant-api/ask",
        json={"question": "What does this page show?", "ui_context": sample_context},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["mock"] is True
    assert "RehabTrace Dashboard" in body["answer"]
    assert "Sessions" in body["answer"]


def test_ask_metric_question_uses_context(client, sample_context):
    res = client.post(
        "/assistant-api/ask",
        json={"question": "What does accuracy mean?", "ui_context": sample_context},
    )
    assert res.status_code == 200
    answer = res.json()["answer"]
    assert "Accuracy" in answer
    # Mock answers must point to the therapist, not interpret clinically.
    assert "therapist" in answer.lower()


def test_ask_action_question_uses_context(client, sample_context):
    res = client.post(
        "/assistant-api/ask",
        json={"question": "How do I sync from pi?", "ui_context": sample_context},
    )
    assert res.status_code == 200
    assert "Sync from Pi" in res.json()["answer"]


def test_empty_question_rejected(client, sample_context):
    res = client.post(
        "/assistant-api/ask",
        json={"question": "", "ui_context": sample_context},
    )
    assert res.status_code == 422


def test_whitespace_question_rejected(client, sample_context):
    res = client.post(
        "/assistant-api/ask",
        json={"question": "   ", "ui_context": sample_context},
    )
    assert res.status_code == 422


def test_missing_question_rejected(client, sample_context):
    res = client.post("/assistant-api/ask", json={"ui_context": sample_context})
    assert res.status_code == 422


def test_question_over_max_length_rejected(client, sample_context):
    res = client.post(
        "/assistant-api/ask",
        json={"question": "x" * (MAX_QUESTION_CHARS + 1), "ui_context": sample_context},
    )
    assert res.status_code == 422


def test_missing_context_defaults_to_empty(client):
    res = client.post("/assistant-api/ask", json={"question": "What does this page show?"})
    assert res.status_code == 200
    assert "cannot determine" in res.json()["answer"].lower()


def test_oversized_context_list_rejected(client, sample_context):
    sample_context["visible_metrics"] = [
        {"label": f"Metric {i}", "value": "1", "help_text": ""} for i in range(50)
    ]
    res = client.post(
        "/assistant-api/ask",
        json={"question": "What does this page show?", "ui_context": sample_context},
    )
    assert res.status_code == 422


def test_gemini_timeout_maps_to_502(client, sample_context, settings, monkeypatch):
    settings.gemini_api_key = "test-key"  # leave mock mode

    async def fake_ask(question, context_block):
        raise AssistantUpstreamError("The assistant took too long to answer. Please try again.")

    monkeypatch.setattr(main, "ask_gemini", fake_ask)
    res = client.post(
        "/assistant-api/ask",
        json={"question": "What does this page show?", "ui_context": sample_context},
    )
    assert res.status_code == 502
    assert "too long" in res.json()["detail"]


def test_gemini_success_path(client, sample_context, settings, monkeypatch):
    settings.gemini_api_key = "test-key"

    async def fake_ask(question, context_block):
        # The prompt block must contain sanitized context, not raw JSON.
        assert "RehabTrace Dashboard" in context_block
        assert "Accuracy" in context_block
        return "This screen shows your recorded sessions."

    monkeypatch.setattr(main, "ask_gemini", fake_ask)
    res = client.post(
        "/assistant-api/ask",
        json={"question": "What does this page show?", "ui_context": sample_context},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["mock"] is False
    assert body["answer"] == "This screen shows your recorded sessions."


def test_long_answer_is_truncated(client, sample_context, settings, monkeypatch):
    settings.gemini_api_key = "test-key"

    async def fake_ask(question, context_block):
        return "word " * 2000

    monkeypatch.setattr(main, "ask_gemini", fake_ask)
    res = client.post(
        "/assistant-api/ask",
        json={"question": "What does this page show?", "ui_context": sample_context},
    )
    assert res.status_code == 200
    assert len(res.json()["answer"]) <= settings.max_answer_chars + 1  # +1 for ellipsis


def test_rate_limit_returns_429(client, sample_context, settings):
    settings.rate_limit_requests = 3
    payload = {"question": "What does this page show?", "ui_context": sample_context}
    for _ in range(3):
        assert client.post("/assistant-api/ask", json=payload).status_code == 200
    res = client.post("/assistant-api/ask", json=payload)
    assert res.status_code == 429
