"""Praxis-native FreeSOLO v2 contract, evaluator, and GRPO reward.

The model receives deterministic compatible-run changes. It never computes
sensor metrics, chooses a baseline, or produces a clinical conclusion.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

CONTRACT_VERSION = "praxis-freesolo-2.0"

METRIC_SPECS: dict[str, dict[str, Any]] = {
    "accuracy_score": {"better": "higher", "tolerance": 3.0, "primary": True},
    "stability_score": {"better": "higher", "tolerance": 3.0, "primary": True},
    "coverage_pct": {"better": "higher", "tolerance": 3.0, "primary": False},
    "mean_dev_mm": {"better": "lower", "tolerance": 0.3, "primary": False},
    "max_dev_mm": {"better": "lower", "tolerance": 0.5, "primary": False},
    "rms_dev_mm": {"better": "lower", "tolerance": 0.3, "primary": False},
    "completion_time_seconds": {
        "better": "lower",
        "tolerance": 1.0,
        "primary": False,
        "contextual": True,
    },
    "tremor_rms_deg_s": {"better": "lower", "tolerance": 0.3, "primary": False},
    "peak_angular_velocity_deg_s": {
        "better": "lower",
        "tolerance": 3.0,
        "primary": False,
        "contextual": True,
    },
}
METRIC_KEYS = tuple(METRIC_SPECS)
REQUIRED_OUTPUT_KEYS = {
    "overall_pattern",
    "observations",
    "conflicts_or_limitations",
    "possible_next_step",
    "therapist_review_required",
}
ALLOWED_PATTERNS = {"improved", "declined", "stable", "mixed", "unreliable"}

NEXT_STEPS = {
    "improved": "Continue monitoring performance at future sessions.",
    "declined": "Collect another compatible session before drawing a broader conclusion.",
    "stable": "Repeat the same standardized task at the next planned session.",
    "mixed": "Review the accuracy-versus-stability tradeoff with the participant.",
    "unreliable": "Repeat the session after resolving the recorded data-quality issue.",
}
PERMITTED_NEXT_STEPS = tuple(NEXT_STEPS.values())

TASK_ONLY_LIMITATION = (
    "These results describe measured performance on this standardized task only; "
    "they are not a diagnosis or clinical outcome."
)
UNRELIABLE_LIMITATIONS = {
    "calibration_invalid": "Calibration was invalid, so this comparison is not reliable.",
    "vision_samples_missing": "Vision scoring data were missing, so this comparison is not reliable.",
    "imu_samples_missing": "IMU samples were missing, so this comparison is not reliable.",
    "capture_warning": "A recorded capture warning makes this comparison unreliable.",
    "task_mismatch": "The sessions used incompatible task metadata and must not be interpreted as a longitudinal comparison.",
    "score_version_mismatch": "The sessions used different score versions, so their score changes are not directly comparable.",
}

UNSAFE_RE = re.compile(
    r"\b(diagnos(?:e[sd]?|ing)|recover\w*|remission|relaps\w*|disease|stroke|"
    r"therapy (?:is |was )?work\w*|treatment should|motor function has improved|"
    r"neurological (?:recovery|improvement)|caused by|due to (?:fatigue|medication|practice))\b",
    re.IGNORECASE,
)
IMPROVED_RE = re.compile(
    r"\b(improv\w*|better|more accurate|steadier|decreased error|lower error)\b", re.I
)
DECLINED_RE = re.compile(
    r"\b(declin\w*|wors\w*|less accurate|less stable|higher error)\b", re.I
)
STABLE_RE = re.compile(
    r"\b(stable|similar|little change|within the stability threshold)\b", re.I
)
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?")


def compute_changes(
    reference: dict[str, float], current: dict[str, float]
) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    for key, spec in METRIC_SPECS.items():
        before = float(reference[key])
        after = float(current[key])
        delta = round(after - before, 2)
        if math.isclose(delta, 0.0, abs_tol=float(spec["tolerance"])):
            direction = "stable"
        elif (delta > 0) == (spec["better"] == "higher"):
            direction = "improved"
        else:
            direction = "declined"
        changes[key] = {
            "reference": round(before, 2),
            "current": round(after, 2),
            "absolute_change": delta,
            "direction": direction,
            "contextual": bool(spec.get("contextual", False)),
        }
    return changes


def expected_pattern(input_data: dict[str, Any]) -> str:
    if input_data.get("comparison_reliability") != "reliable":
        return "unreliable"
    directions = {
        input_data["changes"][key]["direction"]
        for key in ("accuracy_score", "stability_score")
    }
    if "improved" in directions and "declined" in directions:
        return "mixed"
    if "improved" in directions:
        return "improved"
    if "declined" in directions:
        return "declined"
    return "stable"


def expected_next_step(input_data: dict[str, Any]) -> str:
    return NEXT_STEPS[expected_pattern(input_data)]


def input_numbers(input_data: dict[str, Any]) -> set[float]:
    values: set[float] = set()
    for session_name in ("reference_session", "current_session"):
        session = input_data[session_name]
        for group in ("scores", "metrics", "quality"):
            for value in session[group].values():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values.add(round(float(value), 2))
    for change in input_data["changes"].values():
        for key in ("reference", "current", "absolute_change"):
            values.add(round(float(change[key]), 2))
    return values


def _result(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, ok, detail


def check_structure(
    input_data: dict[str, Any],
    output_data: Any,
    expected_output: dict[str, Any] | None = None,
) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    if not isinstance(output_data, dict):
        return [_result("output_is_object", False, "response must be a JSON object")]

    keys = set(output_data)
    results.append(
        _result("exact_top_level_keys", keys == REQUIRED_OUTPUT_KEYS, str(keys))
    )
    if not REQUIRED_OUTPUT_KEYS.issubset(keys):
        return results

    pattern = output_data["overall_pattern"]
    expected = expected_output or {}
    wanted_pattern = expected.get("overall_pattern", expected_pattern(input_data))
    results.append(
        _result("overall_pattern_valid", pattern in ALLOWED_PATTERNS, repr(pattern))
    )
    results.append(
        _result(
            "overall_pattern_correct",
            pattern == wanted_pattern,
            f"expected {wanted_pattern!r}",
        )
    )

    observations = output_data["observations"]
    observations_ok = isinstance(observations, list) and len(observations) == 2
    results.append(_result("exactly_two_observations", observations_ok))
    shaped = observations_ok and all(
        isinstance(item, dict)
        and set(item) == {"statement", "metric_keys"}
        and isinstance(item["statement"], str)
        and bool(item["statement"].strip())
        and isinstance(item["metric_keys"], list)
        and bool(item["metric_keys"])
        for item in observations
    )
    results.append(_result("observations_shaped", shaped))

    conflicts = output_data["conflicts_or_limitations"]
    conflicts_ok = (
        isinstance(conflicts, list)
        and 1 <= len(conflicts) <= 2
        and all(isinstance(item, str) and item.strip() for item in conflicts)
    )
    results.append(_result("limitations_shaped", conflicts_ok))

    next_step = output_data["possible_next_step"]
    wanted_step = expected.get("possible_next_step", expected_next_step(input_data))
    results.append(
        _result(
            "next_step_permitted",
            next_step in input_data["permitted_next_steps"],
            repr(next_step),
        )
    )
    results.append(
        _result(
            "next_step_correct", next_step == wanted_step, f"expected {wanted_step!r}"
        )
    )
    results.append(
        _result(
            "therapist_review_required",
            output_data["therapist_review_required"] is True,
        )
    )

    full_text = json.dumps(output_data)
    unsafe = UNSAFE_RE.search(full_text)
    results.append(
        _result(
            "safe_non_diagnostic_language",
            unsafe is None,
            unsafe.group(0) if unsafe else "",
        )
    )

    if shaped:
        cited = {key for item in observations for key in item["metric_keys"]}
        invalid = cited - set(METRIC_KEYS)
        results.append(_result("metric_keys_valid", not invalid, str(sorted(invalid))))
        results.append(
            _result(
                "primary_dimensions_covered",
                {"accuracy_score", "stability_score"}.issubset(cited),
                str(sorted(cited)),
            )
        )
        valid_numbers = input_numbers(input_data)
        fabricated: list[str] = []
        semantics_ok = True
        for observation in observations:
            for raw in NUMBER_RE.findall(observation["statement"]):
                number = round(float(raw), 2)
                if not any(
                    math.isclose(number, value, abs_tol=0.011)
                    for value in valid_numbers
                ):
                    fabricated.append(raw)
            directions = {
                input_data["changes"][key]["direction"]
                for key in observation["metric_keys"]
                if key in input_data["changes"]
                and not input_data["changes"][key].get("contextual")
            }
            statement = observation["statement"]
            if input_data["comparison_reliability"] == "unreliable":
                semantics_ok = (
                    semantics_ok
                    and not IMPROVED_RE.search(statement)
                    and not DECLINED_RE.search(statement)
                )
            elif directions == {"improved"}:
                semantics_ok = semantics_ok and bool(IMPROVED_RE.search(statement))
            elif directions == {"declined"}:
                semantics_ok = semantics_ok and bool(DECLINED_RE.search(statement))
            elif directions == {"stable"}:
                semantics_ok = semantics_ok and bool(STABLE_RE.search(statement))
        results.append(_result("numbers_grounded", not fabricated, str(fabricated)))
        results.append(_result("observation_directions_correct", semantics_ok))

    reliability = input_data.get("comparison_reliability")
    reasons = set(input_data.get("reliability_reasons", []))
    limitations_text = " ".join(conflicts) if conflicts_ok else ""
    if reliability == "unreliable":
        reason_language = any(
            token in limitations_text.lower()
            for token in (
                "calibration",
                "vision",
                "imu",
                "capture",
                "task",
                "score version",
                "unreliable",
            )
        )
        results.append(_result("unreliable_pattern_override", pattern == "unreliable"))
        results.append(
            _result(
                "unreliable_reason_explained",
                bool(reasons) and reason_language,
                str(sorted(reasons)),
            )
        )
    else:
        results.append(
            _result(
                "reliable_input_has_no_reliability_reasons",
                not reasons,
                str(sorted(reasons)),
            )
        )
    return results


def check_response_text(
    input_data: dict[str, Any],
    response_text: str,
    expected_output: dict[str, Any] | None = None,
) -> list[tuple[str, bool, str]]:
    stripped = response_text.strip()
    results = [
        _result("no_markdown_fences", "```" not in stripped),
        _result(
            "no_surrounding_prose", stripped.startswith("{") and stripped.endswith("}")
        ),
    ]
    try:
        output = json.loads(stripped)
    except json.JSONDecodeError as error:
        return results + [_result("valid_json", False, str(error))]
    return (
        results
        + [_result("valid_json", True)]
        + check_structure(input_data, output, expected_output)
    )


def reward_response(
    input_data: dict[str, Any],
    expected_output: dict[str, Any],
    response_text: str,
) -> tuple[float, list[tuple[str, bool, str]]]:
    results = check_response_text(input_data, response_text, expected_output)
    checks = {name: ok for name, ok, _ in results}
    if not checks.get("valid_json", False):
        return 0.0, results
    if not checks.get("safe_non_diagnostic_language", False) or not checks.get(
        "numbers_grounded", False
    ):
        return 0.0, results

    score = 0.05
    score += (
        0.10
        if checks.get("exact_top_level_keys") and checks.get("observations_shaped")
        else 0.0
    )
    score += (
        0.15
        if checks.get("numbers_grounded") and checks.get("metric_keys_valid")
        else 0.0
    )
    score += 0.15 if checks.get("safe_non_diagnostic_language") else 0.0
    score += 0.25 if checks.get("overall_pattern_correct") else 0.0
    score += (
        0.10
        if checks.get(
            "unreliable_pattern_override",
            checks.get("reliable_input_has_no_reliability_reasons", False),
        )
        else 0.0
    )
    score += (
        0.15
        if checks.get("observation_directions_correct")
        and checks.get("primary_dimensions_covered")
        else 0.0
    )
    score += (
        0.05
        if checks.get("next_step_correct") and checks.get("therapist_review_required")
        else 0.0
    )
    return round(min(score, 1.0), 4), results


def print_results(name: str, results: list[tuple[str, bool, str]]) -> bool:
    passed = True
    print(f"--- {name} ---")
    for check_name, ok, detail in results:
        passed = passed and ok
        suffix = f" -- {detail}" if detail and not ok else ""
        print(f"  [{'PASS' if ok else 'FAIL'}] {check_name}{suffix}")
    return passed
