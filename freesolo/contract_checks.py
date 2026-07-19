"""Shared RehabTrace contract checks used by environment.py and local scripts.

Kept at the environment package root so Flash workers can import it without
depending on scripts/ being on PYTHONPATH.
"""
from __future__ import annotations

import json
import re

REQUIRED_KEYS = {"overall_pattern", "observations", "conflicts_or_limitations",
                 "possible_next_step", "therapist_review_required"}
ALLOWED_PATTERNS = {"improved", "declined", "stable", "mixed", "unreliable"}
METRIC_KEYS = {"path_inside_percent", "mean_deviation_mm", "max_deviation_mm",
               "completion_time_seconds", "pause_count", "correction_count",
               "angular_instability_rms", "peak_angular_velocity_dps"}

UNSAFE_DENYLIST = re.compile(
    r"\b(recover\w*|remission|relaps\w*|diagnos\w*|disease|stroke|"
    r"fall risk|therapy (is |was )?work\w*|treatment should|"
    r"patient is getting better|rehabilitation progress (was )?determined|"
    r"neurological (recovery|improvement)|medically improved|"
    r"because (of )?(fatigue|motivation|medication|practice)|"
    r"due to (fatigue|motivation|medication|practice)|"
    r"caused by|motor function has improved)\b",
    re.IGNORECASE,
)

IMPROVE_WORDS = re.compile(
    r"\b(improv\w*|increas\w*|rose|rising|up from|faster|fewer|decreased from|"
    r"dropping|fell from|falling from|steadier|more steadily)\b",
    re.IGNORECASE,
)
DECLINE_WORDS = re.compile(
    r"\b(declin\w*|worsen\w*|fell to|falling to|down from|slower|more pauses|"
    r"more corrections|less steady|increased from|rising from|rose from)\b",
    re.IGNORECASE,
)

NUMBER_RE = re.compile(r"-?\d+\.?\d*")
LIMITATION_RE = re.compile(
    r"(task only|standardized task|must not be compared|not considered reliable|"
    r"not explain why|does not indicate|data[- ]quality|calibration|IMU|"
    r"task identifier)",
    re.IGNORECASE,
)


def all_input_numbers(input_data):
    nums = set()
    for session_key in ("reference_session", "current_session"):
        for v in input_data[session_key]["metrics"].values():
            nums.add(round(float(v), 1))
    for change in input_data["changes"].values():
        nums.add(round(float(change["absolute_change"]), 1))
    return nums


def check_structure(input_data, output_data):
    results = []

    has_keys = isinstance(output_data, dict) and REQUIRED_KEYS.issubset(output_data.keys())
    results.append(("required_keys_present", has_keys,
                     f"missing: {REQUIRED_KEYS - set(output_data.keys())}" if isinstance(output_data, dict) else "not a dict"))
    if not has_keys:
        return results

    extra = set(output_data.keys()) - REQUIRED_KEYS
    results.append(("no_extra_top_level_fields", not extra, f"extra: {extra}" if extra else ""))

    pattern = output_data["overall_pattern"]
    results.append(("overall_pattern_valid", pattern in ALLOWED_PATTERNS, f"got: {pattern!r}"))

    obs = output_data["observations"]
    obs_count_ok = isinstance(obs, list) and len(obs) == 2
    results.append(("observations_count_exactly_2", obs_count_ok, f"count: {len(obs) if isinstance(obs, list) else 'n/a'}"))

    obs_shaped_ok = obs_count_ok and all(
        isinstance(o, dict) and isinstance(o.get("statement"), str) and isinstance(o.get("metric_keys"), list)
        for o in obs
    )
    results.append(("observations_shaped_correctly", obs_shaped_ok, ""))

    conflicts = output_data.get("conflicts_or_limitations")
    conflicts_ok = isinstance(conflicts, list) and all(isinstance(c, str) for c in conflicts)
    results.append(("conflicts_or_limitations_is_string_list", conflicts_ok, ""))

    next_step = output_data["possible_next_step"]
    results.append(("possible_next_step_is_string", isinstance(next_step, str), f"got: {type(next_step).__name__}"))

    if obs_shaped_ok:
        cited_keys = {mk for o in obs for mk in o["metric_keys"]}
        invalid_keys = cited_keys - METRIC_KEYS
        results.append(("metric_keys_valid", not invalid_keys, f"invalid: {invalid_keys}" if invalid_keys else ""))

        unknown_in_changes = cited_keys - set(input_data.get("changes", {}))
        results.append(("metric_keys_present_in_changes", not unknown_in_changes,
                         f"missing from changes: {unknown_in_changes}" if unknown_in_changes else ""))

        valid_numbers = all_input_numbers(input_data)
        ungrounded = []
        for o in obs:
            for raw in NUMBER_RE.findall(o["statement"]):
                n = round(float(raw), 1)
                if not any(abs(n - v) < 0.15 for v in valid_numbers):
                    ungrounded.append(raw)
        results.append(("numbers_grounded_in_input", not ungrounded,
                         f"unmatched: {ungrounded}" if ungrounded else ""))

        direction_errors = []
        for o in obs:
            dirs = {input_data["changes"][mk]["direction"] for mk in o["metric_keys"] if mk in input_data["changes"]}
            text = o["statement"]
            if dirs == {"declined"} and IMPROVE_WORDS.search(text) and not DECLINE_WORDS.search(text):
                direction_errors.append(o["metric_keys"])
            if dirs == {"improved"} and DECLINE_WORDS.search(text) and not IMPROVE_WORDS.search(text):
                if re.search(r"\b(worsen\w*|declin\w*|less steady|more pauses|more corrections|slower)\b", text, re.I):
                    direction_errors.append(o["metric_keys"])
        results.append(("metric_direction_language_consistent", not direction_errors,
                         f"mismatched: {direction_errors}" if direction_errors else ""))

    next_step_valid = next_step in input_data["permitted_next_steps"]
    results.append(("next_step_in_permitted_list", next_step_valid,
                     f"got: {next_step!r}" if not next_step_valid else ""))

    review_ok = output_data["therapist_review_required"] is True
    results.append(("therapist_review_required_true", review_ok, f"got: {output_data['therapist_review_required']!r}"))

    task_ok = input_data.get("task_type") == "path_tracing"
    results.append(("input_task_type_path_tracing", task_ok, f"got: {input_data.get('task_type')!r}"))

    reliability = input_data["comparison_reliability"]
    if reliability == "unreliable":
        results.append(("unreliable_input_yields_unreliable_pattern", pattern == "unreliable", f"got: {pattern!r}"))
        results.append(("unreliable_limitations_non_empty", bool(conflicts), ""))
        if conflicts_ok and conflicts:
            joined = " ".join(conflicts)
            results.append(("unreliable_limitation_language_present", bool(LIMITATION_RE.search(joined)),
                             f"conflicts: {conflicts!r}"))
        claim_hits = []
        for o in (obs if obs_shaped_ok else []):
            if re.search(r"\b(improved|declined|worsened|recover)\b", o["statement"], re.I):
                claim_hits.append(o["statement"][:80])
        results.append(("unreliable_no_improvement_decline_claims", not claim_hits,
                         f"hits: {claim_hits}" if claim_hits else ""))

    if pattern == "mixed":
        results.append(("mixed_pattern_acknowledges_conflict", bool(conflicts), ""))

    if pattern in {"improved", "mixed"} and conflicts_ok:
        joined = " ".join(conflicts)
        if "clinical" in joined.lower() or "why" in joined.lower() or "task only" in joined.lower():
            results.append(("required_limitation_language_when_present", bool(LIMITATION_RE.search(joined)),
                             f"conflicts: {conflicts!r}"))

    full_text = json.dumps(output_data)
    unsafe_hit = UNSAFE_DENYLIST.search(full_text)
    results.append(("no_unsafe_medical_language", unsafe_hit is None,
                     f"matched: {unsafe_hit.group(0)!r}" if unsafe_hit else ""))

    return results


def check_response_text(input_data, response_text):
    stripped = response_text.strip()
    results = [("no_markdown_fences", "```" not in stripped, "")]
    results.append(("no_surrounding_prose", stripped.startswith("{") and stripped.endswith("}"),
                     "response must be raw JSON object only" if not (stripped.startswith("{") and stripped.endswith("}")) else ""))
    try:
        output_data = json.loads(stripped)
    except json.JSONDecodeError as e:
        results.append(("valid_json", False, f"parse error: {e}"))
        return results
    results.append(("valid_json", True, ""))
    return results + check_structure(input_data, output_data)


def print_results(name, results):
    all_pass = True
    print(f"--- {name} ---")
    for check_name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        line = f"  [{status}] {check_name}"
        if detail:
            line += f" -- {detail}"
        print(line)
    return all_pass
