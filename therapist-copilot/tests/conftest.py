import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config, main, note_writer, pipeline, store, watcher  # noqa: E402


@pytest.fixture(autouse=True)
def settings(monkeypatch, tmp_path):
    """Default (mock-mode) settings with a throwaway store file per test."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    test_settings = config.Settings(_env_file=None, store_path=tmp_path / "reviews.json")
    for module in (config, main, note_writer, pipeline, store, watcher):
        monkeypatch.setattr(module, "get_settings", lambda: test_settings, raising=False)
    # Fresh store and ingest cache per test.
    monkeypatch.setattr(store, "_store", None)
    main._ingested_runs.clear()
    return test_settings


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    # Watcher runs in the lifespan; backend is down in tests, which it tolerates.
    return TestClient(main.app)


def make_run(
    run_id="r1",
    username="margaret",
    accuracy=80.0,
    stability=75.0,
    coverage=90.0,
    tremor=2.0,
    calibration_valid=True,
    imu_samples=400,
    warnings=None,
    received_at="2026-07-19T04:00:00Z",
):
    return {
        "id": run_id,
        "session_id": f"sess-{run_id}",
        "username": username,
        "received_at": received_at,
        "scores": {"accuracy": accuracy, "stability": stability},
        "metrics": {"coverage_pct": coverage, "tremor_rms_deg_s": tremor},
        "quality": {
            "calibration_valid": calibration_valid,
            "imu_samples_received": imu_samples,
            "warnings": warnings or [],
        },
        "timing": {"duration_ms": 42000},
    }


@pytest.fixture
def run_factory():
    return make_run
