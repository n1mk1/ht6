"""Tests for the copilot HTTP API (ingest, inbox, approve, edit)."""


def _ingest(client, run):
    return client.post("/copilot-api/ingest", json=run)


def test_health(client):
    res = client.get("/copilot-api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["mock_mode"] is True
    assert body["runs_processed"] == 0


def test_ingest_clean_run(client, run_factory):
    res = _ingest(client, run_factory())
    assert res.status_code == 201
    item = res.json()
    assert item["priority"] == "routine"
    assert item["quality_verdict"] == "clean"
    assert item["status"] == "pending"
    assert item["note_is_mock"] is True
    assert "pending therapist review" in item["draft_note"]
    # Anonymous ID in the note, never the username.
    assert "P-1" in item["draft_note"]
    assert "margaret" not in item["draft_note"].lower()


def test_ingest_bad_calibration_needs_attention(client, run_factory):
    res = _ingest(client, run_factory(calibration_valid=False))
    assert res.status_code == 201
    item = res.json()
    assert item["priority"] == "needs_attention"
    assert item["quality_verdict"] == "unusable"


def test_ingest_duplicate_rejected(client, run_factory):
    assert _ingest(client, run_factory()).status_code == 201
    assert _ingest(client, run_factory()).status_code == 409


def test_ingest_requires_id(client, run_factory):
    run = run_factory()
    run["id"] = ""
    run["session_id"] = ""
    assert _ingest(client, run).status_code == 422


def test_history_used_across_ingests(client, run_factory):
    _ingest(client, run_factory(run_id="r1", accuracy=85.0))
    res = _ingest(client, run_factory(run_id="r2", accuracy=60.0))
    item = res.json()
    assert item["sessions_compared"] == 1
    assert item["priority"] == "review"


def test_inbox_sorted_by_priority(client, run_factory):
    _ingest(client, run_factory(run_id="ok"))
    _ingest(client, run_factory(run_id="bad", username="arthur", calibration_valid=False))
    inbox = client.get("/copilot-api/inbox").json()
    assert [i["priority"] for i in inbox] == ["needs_attention", "routine"]


def test_approve_flow(client, run_factory):
    item = _ingest(client, run_factory()).json()
    res = client.post(f"/copilot-api/reviews/{item['id']}/approve")
    assert res.status_code == 200
    approved = res.json()
    assert approved["status"] == "approved"
    assert "approved by therapist" in approved["decision_log"][-1].lower()


def test_edit_flow(client, run_factory):
    item = _ingest(client, run_factory()).json()
    res = client.post(
        f"/copilot-api/reviews/{item['id']}/edit",
        json={"note": "Therapist-corrected note."},
    )
    assert res.status_code == 200
    edited = res.json()
    assert edited["status"] == "edited"
    assert edited["draft_note"] == "Therapist-corrected note."


def test_edit_empty_note_rejected(client, run_factory):
    item = _ingest(client, run_factory()).json()
    res = client.post(f"/copilot-api/reviews/{item['id']}/edit", json={"note": ""})
    assert res.status_code == 422


def test_unknown_review_404(client):
    assert client.post("/copilot-api/reviews/nope/approve").status_code == 404


def test_ingest_v1_session_shape(client):
    """Sessions in the Praxis API v1 shape (nested user, created_at) work too."""
    session = {
        "session_id": "session_015856",
        "device_id": "qnx_pi_23",
        "created_at": "2026-07-18T15:58:56Z",
        "user": {"id": 1, "username": "katie", "display_name": "Katie"},
        "scores": {"accuracy": 90.0, "stability": 90.0},
        "metrics": {"coverage_pct": 72.4, "tremor_rms_deg_s": 5.18},
        "quality": {
            "calibration_valid": True,
            "imu_samples_received": 6380,
            "warnings": [],
        },
        "timing": {"duration_ms": 42300},
    }
    res = client.post("/copilot-api/ingest", json=session)
    assert res.status_code == 201
    item = res.json()
    assert item["run_id"] == "qnx_pi_23::session_015856"
    assert item["quality_verdict"] == "clean"
    assert item["received_at"] == "2026-07-18T15:58:56Z"
    assert "katie" not in item["draft_note"].lower()
