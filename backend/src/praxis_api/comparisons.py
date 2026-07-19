from __future__ import annotations

from typing import Any

POLICY_VERSION = "praxis-comparison-1.0.0"

METRICS: dict[str, tuple[str, float]] = {
    "accuracy_score": ("higher", 0.5),
    "stability_score": ("higher", 0.5),
    "coverage_pct": ("higher", 0.5),
    "completion_time_seconds": ("lower", 0.1),
    "mean_dev_mm": ("lower", 0.01),
    "max_dev_mm": ("lower", 0.01),
    "rms_dev_mm": ("lower", 0.01),
    "tremor_rms_deg_s": ("lower", 0.01),
    "gyro_rms_deg_s": ("lower", 0.01),
    "peak_angular_velocity_deg_s": ("lower", 0.01),
}


def compatibility_key(session: dict[str, Any]) -> tuple[str, str, str, str]:
    task = session["task"]
    return (
        str(task.get("type", "")),
        str(task.get("version", "")),
        str(task.get("difficulty", "")),
        str(task.get("hand", task.get("dominant_hand", ""))),
    )


def compare_sessions(reference: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    reference_key = compatibility_key(reference)
    current_key = compatibility_key(current)
    if reference_key != current_key:
        return {
            "policy_version": POLICY_VERSION,
            "compatible": False,
            "reason": "task_type_version_difficulty_or_hand_mismatch",
            "reference_key": reference_key,
            "current_key": current_key,
            "changes": {},
        }

    changes: dict[str, Any] = {}
    for name, (better, tolerance) in METRICS.items():
        before = reference["metrics"].get(name)
        after = current["metrics"].get(name)
        if before is None or after is None:
            continue
        delta = round(float(after) - float(before), 4)
        if abs(delta) <= tolerance:
            direction = "stable"
        elif (delta > 0 and better == "higher") or (delta < 0 and better == "lower"):
            direction = "improved"
        else:
            direction = "declined"
        percent_change = None if float(before) == 0 else round(delta / abs(float(before)) * 100, 2)
        changes[name] = {
            "reference": before,
            "current": after,
            "absolute_change": delta,
            "percent_change": percent_change,
            "direction": direction,
        }

    directions = [value["direction"] for value in changes.values()]
    improved = directions.count("improved")
    declined = directions.count("declined")
    if improved and declined:
        overall = "mixed"
    elif improved:
        overall = "improved"
    elif declined:
        overall = "declined"
    else:
        overall = "stable"
    return {
        "policy_version": POLICY_VERSION,
        "compatible": True,
        "compatibility_key": reference_key,
        "overall": overall,
        "changes": changes,
    }
