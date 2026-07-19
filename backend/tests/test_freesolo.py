from __future__ import annotations

from praxis_api.config import Settings
from praxis_api.freesolo import FreeSoloAdapter, build_input


def complete_session(session_id: str, values: list[float]) -> dict:
    names = [
        "path_inside_percent",
        "mean_dev_mm",
        "max_dev_mm",
        "completion_time_seconds",
        "pause_count",
        "correction_count",
        "angular_instability_rms",
        "peak_angular_velocity_deg_s",
    ]
    return {
        "session_id": session_id,
        "username": "participant-001",
        "created_at": "2026-07-18T09:00:00Z",
        "task": {"type": "path_tracing", "version": "mat_v1", "difficulty": 1},
        "metrics": dict(zip(names, values, strict=True)),
        "quality": {
            "camera_tracking_percent": 98.0,
            "imu_capture_percent": 99.0,
            "calibration_valid": True,
            "dropped_frame_count": 0,
            "dropped_sample_count": 0,
            "warnings": [],
        },
    }


def test_adapter_contract_maps_only_existing_semantic_aliases():
    reference = complete_session("one", [70, 4.8, 12.6, 42.3, 5, 9, 7.1, 31.5])
    current = complete_session("two", [83, 3.1, 9.2, 48.7, 3, 6, 6.4, 28.1])
    model_input, missing = build_input(reference, current)
    assert missing == []
    assert model_input["reference_session"]["metrics"]["mean_deviation_mm"] == 4.8
    assert model_input["changes"]["completion_time_seconds"]["direction"] == "declined"


def test_adapter_marks_actual_qnx_metric_gap_unavailable():
    qnx = {
        "session_id": "qnx",
        "username": "person",
        "created_at": "2026-07-18T09:00:00Z",
        "task": {"type": "path_tracing"},
        "metrics": {"mean_dev_mm": 2.0, "completion_time_seconds": 20.0},
        "quality": {"calibration_valid": True},
    }
    result = FreeSoloAdapter(Settings(freesolo_mode="http")).analyze(qnx, qnx)
    assert result.status == "unavailable"
    assert result.error_code == "missing_required_metrics"
    assert "path_inside_percent" in result.error_detail
    assert result.regression_score is None


def test_development_mock_is_explicitly_labeled_and_blocked_in_production():
    reference = complete_session("one", [70, 4.8, 12.6, 42.3, 5, 9, 7.1, 31.5])
    current = complete_session("two", [83, 3.1, 9.2, 48.7, 3, 6, 6.4, 28.1])
    result = FreeSoloAdapter(Settings(freesolo_mode="mock")).analyze(reference, current)
    assert result.status == "completed"
    assert result.adapter == "development_mock"
    assert result.confidence == 0.0

    try:
        Settings(environment="production", freesolo_mode="mock")
    except ValueError as error:
        assert "development-only" in str(error)
    else:
        raise AssertionError("production mock configuration should fail")
