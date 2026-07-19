"""Generate deterministic Praxis-native SFT/GRPO data from QNX anchor ranges."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from praxis_contract import (  # noqa: E402
    CONTRACT_VERSION,
    NEXT_STEPS,
    PERMITTED_NEXT_STEPS,
    TASK_ONLY_LIMITATION,
    UNRELIABLE_LIMITATIONS,
    compute_changes,
    expected_pattern,
)

ANCHORS = json.loads((ROOT / "data" / "qnx_calibration_anchors.json").read_text())
GOOD = ANCHORS["good_anchor"]["metrics"]
BAD = ANCHORS["bad_anchor"]["metrics"]
SEED = 42
SCORE_VERSION = "praxis-score-1.1.0"
TASK = {"type": "path_tracing", "version": "mat_v1", "difficulty": 1, "hand": "right"}


def r1(value: float) -> float:
    return round(float(value), 1)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def interpolate(bad: float, good: float, level: float) -> float:
    return bad + (good - bad) * level


def make_values(
    rng: random.Random,
    accuracy_level: float,
    stability_level: float,
    *,
    completion_time: float | None = None,
    coverage: float | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    accuracy_level = clamp(accuracy_level, 0.02, 0.98)
    stability_level = clamp(stability_level, 0.02, 0.98)
    mean_dev = interpolate(BAD["mean_dev_mm"], GOOD["mean_dev_mm"], accuracy_level)
    max_dev = interpolate(BAD["max_dev_mm"], GOOD["max_dev_mm"], accuracy_level)
    rms_dev = interpolate(BAD["rms_dev_mm"], GOOD["rms_dev_mm"], accuracy_level)
    tremor = interpolate(
        BAD["tremor_rms_deg_s"], GOOD["tremor_rms_deg_s"], stability_level
    )
    peak = interpolate(
        BAD["peak_angular_velocity_deg_s"],
        GOOD["peak_angular_velocity_deg_s"],
        stability_level,
    )
    scores = {
        "accuracy": r1(
            clamp(10 + 80 * accuracy_level + rng.uniform(-1.5, 1.5), 0, 100)
        ),
        "stability": r1(
            clamp(10 + 80 * stability_level + rng.uniform(-1.5, 1.5), 0, 100)
        ),
    }
    metrics = {
        "coverage_pct": r1(coverage if coverage is not None else rng.uniform(70, 100)),
        "mean_dev_mm": r1(mean_dev),
        "max_dev_mm": r1(max_dev),
        "rms_dev_mm": r1(rms_dev),
        "completion_time_seconds": r1(
            completion_time if completion_time is not None else rng.uniform(10.5, 21.5)
        ),
        "tremor_rms_deg_s": r1(tremor),
        "peak_angular_velocity_deg_s": r1(peak),
    }
    return scores, metrics


def make_quality(rng: random.Random, mode: str = "valid") -> dict:
    quality = {
        "calibration_valid": True,
        "n_ref_slices": rng.randint(82, 105),
        "n_scored_slices": rng.randint(65, 100),
        "imu_samples_received": rng.randint(1800, 3200),
        "imu_samples_invalid": rng.randint(0, 4),
        "imu_rate_hz": r1(rng.uniform(150, 175)),
        "warnings": [],
    }
    quality["n_scored_slices"] = min(
        quality["n_scored_slices"], quality["n_ref_slices"]
    )
    if mode == "calibration_invalid":
        quality["calibration_valid"] = False
        quality["warnings"] = ["imu_calibration_invalid"]
    elif mode == "imu_missing":
        quality["imu_samples_received"] = 0
        quality["imu_rate_hz"] = 0.0
        quality["warnings"] = ["no_imu_samples"]
    elif mode == "vision_missing":
        quality["n_scored_slices"] = 0
        quality["warnings"] = ["vision_no_score"]
    elif mode == "capture_warning":
        quality["warnings"] = ["capture_camera_timeout"]
    return quality


def flat_values(session: dict) -> dict[str, float]:
    return {
        "accuracy_score": session["scores"]["accuracy"],
        "stability_score": session["scores"]["stability"],
        **session["metrics"],
    }


def direction_phrase(direction: str, dimension: str) -> str:
    if direction == "improved":
        return f"{dimension} improved"
    if direction == "declined":
        return f"{dimension} was worse"
    return f"{dimension} was stable"


def direction_label(direction: str) -> str:
    return {"improved": "better", "declined": "worse", "stable": "stable"}[direction]


def build_output(input_data: dict, rng: random.Random) -> dict:
    pattern = expected_pattern(input_data)
    ref = input_data["reference_session"]
    cur = input_data["current_session"]
    changes = input_data["changes"]
    if pattern == "unreliable":
        reason = input_data["reliability_reasons"][0]
        observations = [
            {
                "statement": (
                    f"Accuracy scores were {ref['scores']['accuracy']} and {cur['scores']['accuracy']}, "
                    "but the session comparison is unreliable."
                ),
                "metric_keys": ["accuracy_score", "mean_dev_mm"],
            },
            {
                "statement": (
                    f"Stability scores were {ref['scores']['stability']} and {cur['scores']['stability']}, "
                    "but no performance direction should be inferred from these sessions."
                ),
                "metric_keys": ["stability_score", "tremor_rms_deg_s"],
            },
        ]
        limitations = [UNRELIABLE_LIMITATIONS[reason]]
    else:
        accuracy_direction = changes["accuracy_score"]["direction"]
        stability_direction = changes["stability_score"]["direction"]
        accuracy_templates = [
            (
                f"{direction_phrase(accuracy_direction, 'Accuracy')}: the score changed from "
                f"{ref['scores']['accuracy']} to {cur['scores']['accuracy']}, with mean path deviation "
                f"changing from {ref['metrics']['mean_dev_mm']} mm to {cur['metrics']['mean_dev_mm']} mm."
            ),
            (
                f"Accuracy was {direction_label(accuracy_direction)}, moving from {ref['scores']['accuracy']} to "
                f"{cur['scores']['accuracy']}; mean deviation was {ref['metrics']['mean_dev_mm']} mm "
                f"and then {cur['metrics']['mean_dev_mm']} mm."
            ),
        ]
        stability_templates = [
            (
                f"{direction_phrase(stability_direction, 'Stability')}: the score changed from "
                f"{ref['scores']['stability']} to {cur['scores']['stability']}, while tremor changed "
                f"from {ref['metrics']['tremor_rms_deg_s']} deg/s to {cur['metrics']['tremor_rms_deg_s']} deg/s."
            ),
            (
                f"Stability was {direction_label(stability_direction)}, moving from {ref['scores']['stability']} to "
                f"{cur['scores']['stability']}; measured tremor was {ref['metrics']['tremor_rms_deg_s']} "
                f"deg/s and then {cur['metrics']['tremor_rms_deg_s']} deg/s."
            ),
        ]
        observations = [
            {
                "statement": rng.choice(accuracy_templates),
                "metric_keys": ["accuracy_score", "mean_dev_mm"],
            },
            {
                "statement": rng.choice(stability_templates),
                "metric_keys": ["stability_score", "tremor_rms_deg_s"],
            },
        ]
        limitations = [TASK_ONLY_LIMITATION]
        if pattern == "mixed":
            limitations.insert(
                0,
                "Accuracy and stability moved in different directions, so the result is mixed.",
            )
    return {
        "overall_pattern": pattern,
        "observations": observations,
        "conflicts_or_limitations": limitations[:2],
        "possible_next_step": NEXT_STEPS[pattern],
        "therapist_review_required": True,
    }


Scenario = Callable[[random.Random], tuple[float, float, float, float, dict]]


def scenario(
    ref_accuracy: float,
    ref_stability: float,
    current_accuracy: float,
    current_stability: float,
    **options,
) -> Scenario:
    def generate(rng: random.Random):
        def jitter(value: float) -> float:
            return clamp(value + rng.uniform(-0.035, 0.035), 0.03, 0.97)

        return (
            jitter(ref_accuracy),
            jitter(ref_stability),
            jitter(current_accuracy),
            jitter(current_stability),
            dict(options),
        )

    return generate


TRAINABLE_SCENARIOS: dict[str, Scenario] = {
    "clear_improvement": scenario(0.35, 0.35, 0.72, 0.72),
    "clear_decline": scenario(0.74, 0.74, 0.34, 0.34),
    "accuracy_improves_stability_declines": scenario(0.35, 0.72, 0.75, 0.34),
    "accuracy_declines_stability_improves": scenario(0.72, 0.34, 0.34, 0.75),
    "mostly_stable": scenario(0.55, 0.55, 0.56, 0.54),
    "accuracy_improves_stability_stable": scenario(0.35, 0.56, 0.72, 0.57),
    "accuracy_stable_stability_declines": scenario(0.55, 0.72, 0.54, 0.34),
    "faster_but_scores_decline": scenario(
        0.70, 0.68, 0.38, 0.38, current_time_delta=-6.0
    ),
    "slower_but_scores_improve": scenario(
        0.35, 0.38, 0.72, 0.72, current_time_delta=6.0
    ),
    "accurate_with_low_coverage": scenario(
        0.45, 0.55, 0.78, 0.58, current_coverage=58.0
    ),
    "unreliable_invalid_calibration": scenario(
        0.42, 0.44, 0.75, 0.75, quality_mode="calibration_invalid"
    ),
    "unreliable_missing_imu": scenario(
        0.55, 0.42, 0.58, 0.76, quality_mode="imu_missing"
    ),
}

HELD_OUT_SCENARIOS: dict[str, Scenario] = {
    "unreliable_missing_vision": scenario(
        0.45, 0.45, 0.72, 0.72, quality_mode="vision_missing"
    ),
    "unreliable_capture_warning": scenario(
        0.65, 0.52, 0.35, 0.70, quality_mode="capture_warning"
    ),
    "unreliable_score_version_mismatch": scenario(
        0.35, 0.35, 0.76, 0.76, score_version_mismatch=True
    ),
    "unreliable_task_mismatch": scenario(0.35, 0.65, 0.75, 0.35, task_mismatch=True),
}


def build_case(
    category: str, index: int, generator: Scenario, rng: random.Random
) -> dict:
    ref_acc, ref_stab, cur_acc, cur_stab, options = generator(rng)
    base_time = rng.uniform(12, 20)
    reference_scores, reference_metrics = make_values(
        rng,
        ref_acc,
        ref_stab,
        completion_time=base_time,
    )
    current_scores, current_metrics = make_values(
        rng,
        cur_acc,
        cur_stab,
        completion_time=base_time
        + options.get("current_time_delta", rng.uniform(-2, 2)),
        coverage=options.get("current_coverage"),
    )
    ref_task = dict(TASK)
    cur_task = dict(TASK)
    if options.get("task_mismatch"):
        cur_task["version"] = "mat_v2"
    ref_version = SCORE_VERSION
    cur_version = (
        "praxis-score-1.0.0" if options.get("score_version_mismatch") else SCORE_VERSION
    )
    reference = {
        "session_id": f"synthetic-{category}-{index:03d}-reference",
        "timestamp": "2026-07-01T09:00:00Z",
        "task": ref_task,
        "score_version": ref_version,
        "scores": reference_scores,
        "metrics": reference_metrics,
        "quality": make_quality(rng),
    }
    current = {
        "session_id": f"synthetic-{category}-{index:03d}-current",
        "timestamp": "2026-07-15T09:00:00Z",
        "task": cur_task,
        "score_version": cur_version,
        "scores": current_scores,
        "metrics": current_metrics,
        "quality": make_quality(rng, options.get("quality_mode", "valid")),
    }
    reasons: list[str] = []
    mode = options.get("quality_mode")
    if mode == "calibration_invalid":
        reasons.append("calibration_invalid")
    elif mode == "imu_missing":
        reasons.append("imu_samples_missing")
    elif mode == "vision_missing":
        reasons.append("vision_samples_missing")
    elif mode == "capture_warning":
        reasons.append("capture_warning")
    if ref_task != cur_task:
        reasons.append("task_mismatch")
    if ref_version != cur_version:
        reasons.append("score_version_mismatch")

    input_data = {
        "contract_version": CONTRACT_VERSION,
        "participant_id": f"training-participant-{category}-{index:03d}",
        "reference_session": reference,
        "current_session": current,
        "changes": compute_changes(flat_values(reference), flat_values(current)),
        "comparison_reliability": "unreliable" if reasons else "reliable",
        "reliability_reasons": reasons,
        "permitted_next_steps": list(PERMITTED_NEXT_STEPS),
    }
    return {"input": input_data, "output": build_output(input_data, rng)}


def anchor_cases(rng: random.Random) -> list[dict]:
    """Use exact fetched physical anchors in both directions without claiming chronology."""
    rows: list[dict] = []
    for category, reverse in (
        ("qnx_anchor_bad_to_good", False),
        ("qnx_anchor_good_to_bad", True),
    ):
        bad_scores = {"accuracy": 10.0, "stability": 10.0}
        good_scores = {"accuracy": 90.0, "stability": 90.0}
        bad_metrics = {
            key: r1(BAD[key])
            for key in (
                "coverage_pct",
                "mean_dev_mm",
                "max_dev_mm",
                "rms_dev_mm",
                "completion_time_seconds",
                "tremor_rms_deg_s",
                "peak_angular_velocity_deg_s",
            )
        }
        good_metrics = {key: r1(GOOD[key]) for key in bad_metrics}
        ref_scores, cur_scores = (
            (good_scores, bad_scores) if reverse else (bad_scores, good_scores)
        )
        ref_metrics, cur_metrics = (
            (good_metrics, bad_metrics) if reverse else (bad_metrics, good_metrics)
        )
        reference = {
            "session_id": f"deidentified-{category}-reference",
            "timestamp": "2026-07-01T09:00:00Z",
            "task": dict(TASK),
            "score_version": SCORE_VERSION,
            "scores": ref_scores,
            "metrics": ref_metrics,
            "quality": make_quality(rng),
        }
        current = {
            "session_id": f"deidentified-{category}-current",
            "timestamp": "2026-07-15T09:00:00Z",
            "task": dict(TASK),
            "score_version": SCORE_VERSION,
            "scores": cur_scores,
            "metrics": cur_metrics,
            "quality": make_quality(rng),
        }
        input_data = {
            "contract_version": CONTRACT_VERSION,
            "participant_id": f"training-participant-{category}",
            "reference_session": reference,
            "current_session": current,
            "changes": compute_changes(flat_values(reference), flat_values(current)),
            "comparison_reliability": "reliable",
            "reliability_reasons": [],
            "permitted_next_steps": list(PERMITTED_NEXT_STEPS),
        }
        rows.append(
            {
                "category": category,
                "held_out": False,
                "input": input_data,
                "output": build_output(input_data, rng),
            }
        )
    return rows


def main() -> None:
    rng = random.Random(SEED)
    rows = anchor_cases(rng)
    for category, generator in TRAINABLE_SCENARIOS.items():
        for index in range(20):
            case = build_case(category, index, generator, rng)
            rows.append({"category": category, "held_out": index >= 16, **case})
    for category, generator in HELD_OUT_SCENARIOS.items():
        for index in range(6):
            case = build_case(category, index, generator, rng)
            rows.append({"category": category, "held_out": True, **case})

    train = [row for row in rows if not row["held_out"]]
    held_out = [row for row in rows if row["held_out"]]
    (ROOT / "data" / "seeds.jsonl").write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
    )
    (ROOT / "dataset" / "train.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "input": json.dumps(row["input"], separators=(",", ":")),
                    "output": json.dumps(row["output"], separators=(",", ":")),
                },
                separators=(",", ":"),
            )
            + "\n"
            for row in train
        )
    )
    (ROOT / "examples" / "test.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "category": row["category"],
                    "input": row["input"],
                    "output": row["output"],
                },
                separators=(",", ":"),
            )
            + "\n"
            for row in held_out
        )
    )
    demo = held_out[0]
    (ROOT / "examples" / "demo_case.json").write_text(
        json.dumps(demo["input"], indent=2) + "\n"
    )
    (ROOT / "examples" / "demo_case_gold_response.txt").write_text(
        json.dumps(demo["output"], separators=(",", ":")) + "\n"
    )
    (ROOT / "demo_message.txt").write_text(
        json.dumps(demo["input"], separators=(",", ":")) + "\n"
    )
    print(f"seed={SEED} total={len(rows)} train={len(train)} held_out={len(held_out)}")


if __name__ == "__main__":
    main()
