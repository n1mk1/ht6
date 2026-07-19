from __future__ import annotations

import copy
import json


def post(client, payload):
    return client.post("/api/v1/qnx/sessions", json=payload)


def test_contract_fixture_ingests_and_preserves_original(client, app, payload):
    response = post(client, payload)
    assert response.status_code == 201
    assert response.json()["created"] is True
    assert response.json()["model_status"] == "pending"

    detail = client.get("/api/v1/sessions/qnx_pi_23/session_015856")
    assert detail.status_code == 200
    body = detail.json()
    assert body["schema_version"] == "3.0"
    assert body["task"] == payload["task"]
    assert body["metrics"]["mean_dev_mm"] == 1.86
    assert body["quality"]["imu_samples_received"] == 6380
    assert body["trace"]["reference"] == payload["trace"]["reference"]
    assert body["original_payload"] == payload
    assert body["model_result"]["error_code"] == "no_reference_session"

    with app.state.database.connect() as connection:
        row = connection.execute("SELECT * FROM sessions").fetchone()
        assert row["coverage_pct"] == 72.4
        assert json.loads(row["quality_json"])["calibration_valid"] is True


def test_ingestion_is_idempotent_by_session_and_device(client, app, payload):
    assert post(client, payload).status_code == 201
    duplicate = post(client, payload)
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False
    with app.state.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM model_results").fetchone()[0] == 1


def test_identity_collision_is_clear_non_retryable_conflict(client, payload):
    assert post(client, payload).status_code == 201
    changed = copy.deepcopy(payload)
    changed["metrics"]["mean_dev_mm"] = 9.9
    response = post(client, changed)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "session_identity_conflict"
    assert response.json()["detail"]["retryable"] is False


def test_schema_validation_rejects_unsupported_or_incomplete_payload(client, payload):
    unsupported = copy.deepcopy(payload)
    unsupported["schema_version"] = "2.0"
    response = post(client, unsupported)
    assert response.status_code == 422
    assert "expected 3.0" in response.text

    incomplete = copy.deepcopy(payload)
    del incomplete["task"]["version"]
    assert post(client, incomplete).status_code == 422


def test_current_qnx_default_route_remains_compatible(client, payload):
    response = client.post("/api/runs", json=payload)
    assert response.status_code == 201


def test_username_resolution_connects_future_qnx_sessions(client, payload):
    first = client.post("/api/v1/users/resolve", json={"username": "  NewPerson  "})
    assert first.status_code == 201
    user_id = first.json()["user"]["id"]
    assert first.json()["user"]["session_count"] == 0

    again = client.post("/api/v1/users/resolve", json={"username": "newperson"})
    assert again.status_code == 200
    assert again.json()["user"]["id"] == user_id

    linked = copy.deepcopy(payload)
    linked["username"] = "NEWPERSON"
    assert post(client, linked).status_code == 201
    history = client.get(f"/api/v1/users/{user_id}/sessions").json()
    assert history[0]["session_id"] == payload["session_id"]


def test_compatible_sessions_get_deterministic_comparison(client, payload):
    first = copy.deepcopy(payload)
    second = copy.deepcopy(payload)
    second["session_id"] = "session_020000"
    second["created_at"] = "2026-07-19T16:00:00Z"
    second["metrics"]["mean_dev_mm"] = 1.4
    second["metrics"]["completion_time_seconds"] = 39.0
    second["scores"]["accuracy"] = 94.0
    assert post(client, first).status_code == 201
    assert post(client, second).status_code == 201

    detail = client.get("/api/v1/sessions/qnx_pi_23/session_020000").json()
    comparison = detail["deterministic_comparison"]
    assert comparison["compatible"] is True
    assert comparison["changes"]["mean_dev_mm"]["direction"] == "improved"
    assert comparison["changes"]["completion_time_seconds"]["absolute_change"] == -3.3

    pair = client.get(
        "/api/v1/comparisons",
        params={
            "reference_device_id": "qnx_pi_23",
            "reference_session_id": "session_015856",
            "current_device_id": "qnx_pi_23",
            "current_session_id": "session_020000",
        },
    )
    assert pair.status_code == 200
    assert pair.json()["deterministic_comparison"]["policy_version"] == "praxis-comparison-1.0.0"


def test_pairwise_comparison_rejects_incompatible_task_metadata(client, payload):
    first = copy.deepcopy(payload)
    second = copy.deepcopy(payload)
    second["session_id"] = "session_left"
    second["created_at"] = "2026-07-20T16:00:00Z"
    second["task"]["hand"] = "left"
    post(client, first)
    post(client, second)
    response = client.get(
        "/api/v1/comparisons",
        params={
            "reference_device_id": "qnx_pi_23",
            "reference_session_id": "session_015856",
            "current_device_id": "qnx_pi_23",
            "current_session_id": "session_left",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "incompatible_sessions"


def test_user_history_latest_and_trends(client, payload):
    post(client, payload)
    users = client.get("/api/v1/users").json()
    assert users[0]["username"] == "KatieCalibrationGood"
    user_id = users[0]["id"]
    assert (
        client.get(f"/api/v1/users/{user_id}/sessions").json()[0]["session_id"] == "session_015856"
    )
    assert client.get(f"/api/v1/users/{user_id}/sessions/latest").status_code == 200
    trends = client.get(f"/api/v1/users/{user_id}/trends").json()["series"]
    assert trends[0]["accuracy"] == 90.0


def test_earliest_compatible_baseline_endpoint(client, payload):
    first = copy.deepcopy(payload)
    second = copy.deepcopy(payload)
    second["session_id"] = "session_baseline_current"
    second["created_at"] = "2026-07-22T09:00:00Z"
    second["scores"]["accuracy"] = 94.0
    second["metrics"]["accuracy_score"] = 94.0
    post(client, first)
    post(client, second)
    user_id = client.get("/api/v1/users").json()[0]["id"]
    response = client.get(f"/api/v1/users/{user_id}/comparisons/baseline")
    assert response.status_code == 200
    body = response.json()
    assert body["baseline"]["session_id"] == "session_015856"
    assert body["current"]["session_id"] == "session_baseline_current"
    assert body["deterministic_comparison"]["compatible"] is True
