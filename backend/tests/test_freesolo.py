from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from praxis_api.config import Settings
from praxis_api.freesolo import (
    CONTRACT_VERSION,
    NEXT_STEPS,
    FreeSoloAdapter,
    _validate_response,
    build_input,
)


def qnx_session() -> dict:
    fixture = Path(__file__).parent / "fixtures" / "qnx_session_v3.json"
    return json.loads(fixture.read_text())


def current_session(reference: dict) -> dict:
    current = copy.deepcopy(reference)
    current["session_id"] = "session_020000"
    current["created_at"] = "2026-07-19T16:00:00Z"
    current["scores"]["accuracy"] = 82.0
    current["scores"]["stability"] = 76.0
    current["metrics"].update(
        {
            "coverage_pct": 68.0,
            "mean_dev_mm": 2.8,
            "max_dev_mm": 7.1,
            "rms_dev_mm": 3.0,
            "completion_time_seconds": 45.0,
            "tremor_rms_deg_s": 7.2,
            "peak_angular_velocity_deg_s": 36.0,
        }
    )
    return current


def valid_decline_response() -> dict:
    return {
        "overall_pattern": "declined",
        "observations": [
            {
                "statement": "Accuracy declined from 90.0 to 82.0 on this task.",
                "metric_keys": ["accuracy_score"],
            },
            {
                "statement": "Stability declined from 90.0 to 76.0 on this task.",
                "metric_keys": ["stability_score"],
            },
        ],
        "conflicts_or_limitations": [
            "These measurements describe this standardized task only and are not a diagnosis."
        ],
        "possible_next_step": NEXT_STEPS["declined"],
        "therapist_review_required": True,
    }


def test_adapter_contract_maps_the_real_qnx_v3_fixture():
    reference = qnx_session()
    model_input, missing = build_input(reference, current_session(reference))

    assert missing == []
    assert model_input is not None
    assert model_input["contract_version"] == CONTRACT_VERSION
    assert model_input["reference_session"]["metrics"]["mean_dev_mm"] == 1.86
    assert model_input["reference_session"]["scores"]["accuracy"] == 90.0
    assert model_input["changes"]["completion_time_seconds"]["direction"] == "declined"


def test_adapter_marks_missing_real_qnx_fields_unavailable():
    session = qnx_session()
    del session["metrics"]["coverage_pct"]
    result = FreeSoloAdapter(Settings(freesolo_mode="http")).analyze(session, session)

    assert result.status == "unavailable"
    assert result.error_code == "missing_required_metrics"
    assert "coverage_pct" in result.error_detail
    assert result.regression_score is None


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda session: session["quality"].update(calibration_valid=False), "calibration_invalid"),
        (
            lambda session: session["scores"].update(version="praxis-score-2.0.0"),
            "score_version_mismatch",
        ),
    ],
)
def test_quality_and_score_version_mismatches_make_comparison_unreliable(mutation, reason):
    reference = qnx_session()
    current = current_session(reference)
    mutation(current)
    model_input, missing = build_input(reference, current)

    assert missing == []
    assert model_input is not None
    assert model_input["comparison_reliability"] == "unreliable"
    assert reason in model_input["reliability_reasons"]


def test_backend_rejects_semantically_wrong_model_output():
    reference = qnx_session()
    model_input, missing = build_input(reference, current_session(reference))
    assert missing == [] and model_input is not None

    _validate_response(valid_decline_response(), model_input)
    wrong = valid_decline_response()
    wrong["overall_pattern"] = "stable"
    with pytest.raises(ValueError, match="incorrect overall_pattern"):
        _validate_response(wrong, model_input)


def test_backend_rejects_fabricated_numbers_and_clinical_claims():
    reference = qnx_session()
    model_input, _ = build_input(reference, current_session(reference))
    assert model_input is not None

    fabricated = valid_decline_response()
    fabricated["observations"][0]["statement"] = "Accuracy declined to 999.0."
    with pytest.raises(ValueError, match="ungrounded number"):
        _validate_response(fabricated, model_input)

    unsafe = valid_decline_response()
    unsafe["conflicts_or_limitations"] = ["This diagnoses a neurological improvement."]
    with pytest.raises(ValueError, match="unsafe clinical language"):
        _validate_response(unsafe, model_input)


def test_development_mock_is_explicitly_labeled_and_blocked_in_production():
    reference = qnx_session()
    result = FreeSoloAdapter(Settings(freesolo_mode="mock")).analyze(
        reference, current_session(reference)
    )
    assert result.status == "completed"
    assert result.adapter == "development_mock"
    assert result.confidence == 0.0

    with pytest.raises(ValueError, match="development-only"):
        Settings(environment="production", freesolo_mode="mock")
