"""The copilot pipeline: deterministic triage, comparison, and prioritization.

Every decision that affects a participant (quality verdict, priority) is
rule-based and auditable. The LLM is only used afterwards, to phrase the
draft note. Each step appends to a human-readable decision log shown in the
Therapist Inbox.
"""

from .config import get_settings
from .schemas import MetricDelta, QualityVerdict, ReviewItem

# Metrics compared against the participant's own history: (label, path)
COMPARED_METRICS = [
    ("Accuracy", ("scores", "accuracy")),
    ("Stability", ("scores", "stability")),
    ("Coverage %", ("metrics", "coverage_pct")),
    ("Tremor RMS (deg/s)", ("metrics", "tremor_rms_deg_s")),
]


def _get(run: dict, path: tuple[str, str]) -> float | None:
    value = (run.get(path[0]) or {}).get(path[1])
    return float(value) if isinstance(value, (int, float)) else None


def assess_quality(run: dict) -> tuple[QualityVerdict, list[str]]:
    """Rule-based data-quality gate. Returns (verdict, reasons)."""
    settings = get_settings()
    quality = run.get("quality") or {}
    reasons: list[str] = []

    calibration = quality.get("calibration_valid")
    imu_samples = quality.get("imu_samples_received")
    warnings = quality.get("warnings") or []

    if calibration is False:
        reasons.append("Calibration was invalid — stability scores are unreliable.")
    if isinstance(imu_samples, (int, float)) and imu_samples < settings.min_imu_samples:
        reasons.append(
            f"Only {int(imu_samples)} IMU samples received "
            f"(minimum {settings.min_imu_samples}) — movement data is incomplete."
        )
    if _get(run, ("scores", "accuracy")) is None:
        reasons.append("No accuracy score — the camera may not have detected the pattern.")

    if reasons:
        return "unusable", reasons

    if warnings:
        return "usable_with_warnings", [f"Recorded with warnings: {', '.join(warnings)}."]

    return "clean", []


def compare_history(run: dict, previous_runs: list[dict]) -> tuple[list[MetricDelta], int]:
    """Compare this run's metrics with the participant's recent average."""
    settings = get_settings()
    history = previous_runs[: settings.history_window]
    deltas: list[MetricDelta] = []

    for label, path in COMPARED_METRICS:
        current = _get(run, path)
        if current is None:
            continue
        past = [v for r in history if (v := _get(r, path)) is not None]
        if not past:
            continue
        avg = sum(past) / len(past)
        deltas.append(
            MetricDelta(
                label=label,
                current=round(current, 1),
                participant_avg=round(avg, 1),
                delta=round(current - avg, 1),
            )
        )

    return deltas, len(history)


def decide_priority(verdict: QualityVerdict, deltas: list[MetricDelta]) -> str:
    settings = get_settings()
    if verdict == "unusable":
        return "needs_attention"
    if any(abs(d.delta) >= settings.review_delta_threshold for d in deltas):
        return "review"
    return "routine"


def anonymize(username: str, known: dict[str, str]) -> str:
    """Map usernames to stable anonymous IDs (P-1, P-2, ...)."""
    name = username or "anonymous"
    if name not in known:
        known[name] = f"P-{len(known) + 1}"
    return known[name]


def build_decision_log(
    participant_id: str,
    verdict: QualityVerdict,
    reasons: list[str],
    deltas: list[MetricDelta],
    sessions_compared: int,
    priority: str,
) -> list[str]:
    log = [f"New session received for participant {participant_id}."]

    if verdict == "clean":
        log.append("Checked data quality — calibration valid, sensor data complete. Usable.")
    elif verdict == "usable_with_warnings":
        log.append(f"Checked data quality — usable, with caveats. {' '.join(reasons)}")
    else:
        log.append(f"Checked data quality — session unusable. {' '.join(reasons)}")
        log.append("Recommended asking the participant to redo this session.")

    if sessions_compared == 0:
        log.append("No previous sessions on record — this is the participant's baseline.")
    else:
        notable = [d for d in deltas if abs(d.delta) >= get_settings().review_delta_threshold]
        if notable:
            changes = ", ".join(
                f"{d.label} {'up' if d.delta > 0 else 'down'} {abs(d.delta):.0f} "
                f"vs. their average of {d.participant_avg:.0f}"
                for d in notable
            )
            log.append(
                f"Compared with the participant's last {sessions_compared} "
                f"session{'s' if sessions_compared != 1 else ''} — notable change: {changes}."
            )
        else:
            log.append(
                f"Compared with the participant's last {sessions_compared} "
                f"session{'s' if sessions_compared != 1 else ''} — metrics within their usual range."
            )

    priority_label = {
        "needs_attention": "Needs attention",
        "review": "Review",
        "routine": "Routine",
    }[priority]
    log.append(f"Drafted a progress note. Priority: {priority_label}.")
    return log


def process_run(
    run: dict,
    previous_runs: list[dict],
    participant_ids: dict[str, str],
) -> ReviewItem:
    """Run the full deterministic pipeline (note text is filled in afterwards)."""
    participant_id = anonymize(run.get("username", ""), participant_ids)
    verdict, reasons = assess_quality(run)
    deltas, sessions_compared = compare_history(run, previous_runs)
    priority = decide_priority(verdict, deltas)
    log = build_decision_log(
        participant_id, verdict, reasons, deltas, sessions_compared, priority
    )

    run_id = run.get("id") or run.get("session_id") or "unknown"
    return ReviewItem(
        id=f"rev-{run_id}",
        run_id=str(run_id),
        participant_id=participant_id,
        received_at=run.get("received_at") or "",
        priority=priority,
        quality_verdict=verdict,
        quality_reasons=reasons,
        deltas=deltas,
        sessions_compared=sessions_compared,
        decision_log=log,
    )
