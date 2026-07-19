"""Tests for the deterministic pipeline rules."""

from server.pipeline import (
    anonymize,
    assess_quality,
    compare_history,
    decide_priority,
    process_run,
)


def test_clean_run_is_clean(run_factory):
    verdict, reasons = assess_quality(run_factory())
    assert verdict == "clean"
    assert reasons == []


def test_invalid_calibration_is_unusable(run_factory):
    verdict, reasons = assess_quality(run_factory(calibration_valid=False))
    assert verdict == "unusable"
    assert any("Calibration" in r for r in reasons)


def test_low_imu_samples_is_unusable(run_factory):
    verdict, reasons = assess_quality(run_factory(imu_samples=10))
    assert verdict == "unusable"
    assert any("IMU samples" in r for r in reasons)


def test_missing_accuracy_is_unusable(run_factory):
    run = run_factory()
    run["scores"]["accuracy"] = None
    verdict, reasons = assess_quality(run)
    assert verdict == "unusable"


def test_warnings_flag_caveats(run_factory):
    verdict, reasons = assess_quality(run_factory(warnings=["low light"]))
    assert verdict == "usable_with_warnings"
    assert "low light" in reasons[0]


def test_history_comparison_computes_deltas(run_factory):
    current = run_factory(run_id="r3", accuracy=60.0)
    history = [
        run_factory(run_id="r1", accuracy=80.0),
        run_factory(run_id="r2", accuracy=90.0),
    ]
    deltas, compared = compare_history(current, history)
    assert compared == 2
    acc = next(d for d in deltas if d.label == "Accuracy")
    assert acc.participant_avg == 85.0
    assert acc.delta == -25.0


def test_no_history_means_baseline(run_factory):
    deltas, compared = compare_history(run_factory(), [])
    assert compared == 0
    assert deltas == []


def test_priority_rules(run_factory, settings):
    from server.schemas import MetricDelta

    big = MetricDelta(label="Accuracy", current=60, participant_avg=85, delta=-25)
    small = MetricDelta(label="Accuracy", current=84, participant_avg=85, delta=-1)

    assert decide_priority("unusable", []) == "needs_attention"
    assert decide_priority("clean", [big]) == "review"
    assert decide_priority("clean", [small]) == "routine"
    assert decide_priority("usable_with_warnings", [small]) == "routine"


def test_anonymize_is_stable():
    known = {}
    assert anonymize("margaret", known) == "P-1"
    assert anonymize("arthur", known) == "P-2"
    assert anonymize("margaret", known) == "P-1"


def test_process_run_builds_full_review(run_factory):
    ids = {}
    item = process_run(
        run_factory(run_id="r2", accuracy=60.0),
        [run_factory(run_id="r1", accuracy=85.0)],
        ids,
    )
    assert item.participant_id == "P-1"
    assert item.priority == "review"
    assert item.sessions_compared == 1
    # Decision log tells the whole story without exposing the username.
    log_text = " ".join(item.decision_log)
    assert "P-1" in log_text
    assert "margaret" not in log_text
    assert "Priority: Review" in log_text


def test_unusable_run_recommends_redo(run_factory):
    item = process_run(run_factory(calibration_valid=False), [], {})
    assert item.priority == "needs_attention"
    assert any("redo" in step for step in item.decision_log)
