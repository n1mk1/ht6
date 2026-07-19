"""RehabTrace dataset generator v2: deterministic, seeded, mechanically grounded,
with phrasing diversity to avoid the repetition-attractor bug found in v1
(where ~100/207 rows shared one near-verbatim sentence template).

Usage: python3 scripts/generate_dataset.py
"""
from __future__ import annotations

import json
import random

HIGHER_BETTER = {"path_inside_percent"}
EPSILON = {
    "path_inside_percent": 2.0, "mean_deviation_mm": 0.3, "max_deviation_mm": 0.3,
    "completion_time_seconds": 2.0, "pause_count": 1.5, "correction_count": 1.5,
    "angular_instability_rms": 0.3, "peak_angular_velocity_dps": 1.0,
}

NEXT_STEPS_POOL = [
    "Repeat the same standardized task at the next planned session.",
    "Review the accuracy-versus-speed tradeoff with the participant.",
    "Confirm that the same task setup and calibration are used next time.",
    "Collect another session before drawing a broader conclusion.",
    "Continue monitoring performance at future sessions.",
    "Review the movement-stability change with the participant.",
]

# Fixed conflict/limitation phrases — also used as guided-decoding enums.
CONFLICTS_POOL = [
    "These results describe measured performance on this standardized task only.",
    "The task was completed more quickly, but path accuracy and deviation were worse.",
    "Accuracy improved, but the task was completed more slowly.",
    "Tracing accuracy improved, but movement stability during the task was worse.",
    "The current session's calibration did not pass validation, so this comparison is not considered reliable.",
    "This reflects a change in standardized task performance only and does not indicate a clinical outcome or confirm that therapy caused the change.",
    "These results describe measured performance on this standardized task only and do not explain why the values changed.",
    "Reference and current sessions use different task identifiers and must not be compared.",
    "Tracing accuracy was stable, but movement stability during the task was notably worse.",
    "IMU data capture for the current session was well below a usable threshold, so movement-quality measurements are not considered reliable.",
]


def r1(x):
    return round(x, 1)


def compute_changes(ref, cur):
    changes = {}
    for key in ref:
        diff = round(cur[key] - ref[key], 2)
        eps = EPSILON[key]
        if abs(diff) <= eps:
            direction = "stable"
        elif key in HIGHER_BETTER:
            direction = "improved" if diff > 0 else "declined"
        else:
            direction = "improved" if diff < 0 else "declined"
        changes[key] = {"absolute_change": diff, "direction": direction}
    return changes


def compute_reliability(ref_q, cur_q):
    for q in (ref_q, cur_q):
        if not q["calibration_valid"]:
            return "unreliable"
        if q["camera_tracking_percent"] < 85 or q["imu_capture_percent"] < 85:
            return "unreliable"
        if q["dropped_frame_count"] > 15 or q["dropped_sample_count"] > 15:
            return "unreliable"
    return "reliable"


def quality(camera=97.0, imu=98.0, calib=True, frames=3, samples=2, warnings=None):
    return {
        "camera_tracking_percent": camera, "imu_capture_percent": imu,
        "calibration_valid": calib, "dropped_frame_count": frames,
        "dropped_sample_count": samples, "warnings": warnings or [],
    }


def pick_next_steps(rng, correct, n=3):
    others = [s for s in NEXT_STEPS_POOL if s != correct]
    steps = rng.sample(others, k=n - 1) + [correct]
    rng.shuffle(steps)
    return steps


def base_quality(rng):
    return quality(camera=r1(rng.uniform(94, 99.5)), imu=r1(rng.uniform(95, 99.8)),
                    calib=True, frames=rng.randint(0, 5), samples=rng.randint(0, 4))


def accuracy_deviation_phrase(rng, ref_a, cur_a, ref_d, cur_d, improved):
    if improved:
        templates = [
            f"Path accuracy increased from {ref_a}% to {cur_a}%, while mean deviation decreased from {ref_d} mm to {cur_d} mm.",
            f"Tracing accuracy rose from {ref_a}% to {cur_a}%, with mean deviation dropping from {ref_d} mm to {cur_d} mm.",
            f"The participant traced {cur_a}% of the path inside tolerance, up from {ref_a}%, and mean deviation fell from {ref_d} mm to {cur_d} mm.",
            f"Accuracy improved to {cur_a}% from {ref_a}%, alongside a reduction in mean deviation from {ref_d} mm to {cur_d} mm.",
        ]
    else:
        templates = [
            f"Path accuracy decreased from {ref_a}% to {cur_a}%, while mean deviation increased from {ref_d} mm to {cur_d} mm.",
            f"Tracing accuracy fell from {ref_a}% to {cur_a}%, with mean deviation rising from {ref_d} mm to {cur_d} mm.",
            f"The participant traced {cur_a}% of the path inside tolerance, down from {ref_a}%, and mean deviation increased from {ref_d} mm to {cur_d} mm.",
            f"Accuracy declined to {cur_a}% from {ref_a}%, alongside a rise in mean deviation from {ref_d} mm to {cur_d} mm.",
        ]
    return rng.choice(templates)


def completion_time_counts_phrase(rng, ref_t, cur_t, ref_p, cur_p, ref_c, cur_c, improved):
    if improved:
        templates = [
            f"Completion time decreased from {ref_t} to {cur_t} seconds, with fewer pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}).",
            f"The task was finished faster, in {cur_t} seconds versus {ref_t}, alongside fewer pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}).",
            f"Completion time improved to {cur_t} seconds (from {ref_t}); pauses dropped from {ref_p} to {cur_p} and corrections from {ref_c} to {cur_c}.",
        ]
    else:
        templates = [
            f"Completion time increased from {ref_t} to {cur_t} seconds, with more pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}).",
            f"The task took longer to finish, {cur_t} seconds versus {ref_t}, alongside more pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}).",
            f"Completion time worsened to {cur_t} seconds (from {ref_t}); pauses rose from {ref_p} to {cur_p} and corrections from {ref_c} to {cur_c}.",
        ]
    return rng.choice(templates)


def completion_time_only_phrase(rng, ref_t, cur_t, improved):
    if improved:
        templates = [
            f"Completion time decreased from {ref_t} to {cur_t} seconds.",
            f"The task was completed faster, in {cur_t} seconds versus {ref_t}.",
            f"Completion time improved to {cur_t} seconds, down from {ref_t}.",
        ]
    else:
        templates = [
            f"Completion time increased from {ref_t} to {cur_t} seconds.",
            f"The task took longer to complete, {cur_t} seconds versus {ref_t}.",
            f"Completion time rose to {cur_t} seconds, up from {ref_t}.",
        ]
    return rng.choice(templates)


def stability_phrase(rng, ref_ai, cur_ai, improved):
    if improved:
        templates = [
            f"Movement stability improved, with angular instability decreasing from {ref_ai} to {cur_ai}.",
            f"Angular instability dropped from {ref_ai} to {cur_ai}, indicating steadier tool handling.",
            f"The tool was held more steadily, with angular instability falling from {ref_ai} to {cur_ai}.",
        ]
    else:
        templates = [
            f"Movement stability declined, with angular instability increasing from {ref_ai} to {cur_ai}.",
            f"Angular instability rose from {ref_ai} to {cur_ai}, indicating less steady tool handling.",
            f"The tool was held less steadily, with angular instability increasing from {ref_ai} to {cur_ai}.",
        ]
    return rng.choice(templates)


def stability_with_peak_phrase(rng, ref_ai, cur_ai, ref_pv, cur_pv, improved):
    if improved:
        templates = [
            f"Angular instability decreased from {ref_ai} to {cur_ai}, and peak angular velocity decreased from {ref_pv} to {cur_pv} degrees per second.",
            f"Movement was steadier: angular instability fell to {cur_ai} (from {ref_ai}) and peak angular velocity fell to {cur_pv} (from {ref_pv}) degrees per second.",
        ]
    else:
        templates = [
            f"Angular instability increased from {ref_ai} to {cur_ai}, and peak angular velocity increased from {ref_pv} to {cur_pv} degrees per second.",
            f"Movement was less steady: angular instability rose to {cur_ai} (from {ref_ai}) and peak angular velocity rose to {cur_pv} (from {ref_pv}) degrees per second.",
        ]
    return rng.choice(templates)


def movement_quality_counts_phrase(rng, ref_p, cur_p, ref_c, cur_c, improved):
    if improved:
        templates = [
            f"Movement quality improved, with fewer pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}).",
            f"Fewer pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}) suggest steadier movement quality.",
        ]
    else:
        templates = [
            f"Movement quality declined, with more pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}).",
            f"More pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}) suggest less steady movement quality.",
        ]
    return rng.choice(templates)


def secondary_time_counts_stability_phrase(rng, ref_t, cur_t, ref_p, cur_p, ref_c, cur_c, ref_ai, cur_ai, improved):
    if improved:
        templates = [
            f"Completion time decreased from {ref_t} to {cur_t} seconds, with fewer pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}), and angular instability fell from {ref_ai} to {cur_ai}.",
            f"The task was finished faster, in {cur_t} seconds versus {ref_t}, with fewer pauses and corrections, and steadier movement (angular instability {ref_ai} to {cur_ai}).",
        ]
    else:
        templates = [
            f"Completion time increased from {ref_t} to {cur_t} seconds, with more pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}), and angular instability rose from {ref_ai} to {cur_ai}.",
            f"The task took longer, {cur_t} seconds versus {ref_t}, with more pauses and corrections, and less steady movement (angular instability {ref_ai} to {cur_ai}).",
        ]
    return rng.choice(templates)


def secondary_time_stability_phrase(ref_t, cur_t, time_improved, ref_ai, cur_ai, stability_improved):
    time_word = "decreased" if time_improved else "increased"
    stab_desc = "steadier, with angular instability falling" if stability_improved else "less steady, with angular instability rising"
    return f"Completion time {time_word} from {ref_t} to {cur_t} seconds; movement quality was {stab_desc} from {ref_ai} to {cur_ai}."


def secondary_time_stable_phrase(rng, ref_t, cur_t, ref_ai, cur_ai):
    templates = [
        f"Completion time was stable ({ref_t} versus {cur_t} seconds), and angular instability showed only small differences ({ref_ai} versus {cur_ai}).",
        f"Both completion time ({cur_t} vs {ref_t} seconds) and angular instability ({cur_ai} vs {ref_ai}) were largely unchanged.",
    ]
    return rng.choice(templates)


def secondary_counts_stability_phrase(ref_p, cur_p, ref_c, cur_c, ref_ai, cur_ai, ref_pv, cur_pv, improved):
    if improved:
        return f"Movement quality improved, with fewer pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}), and angular instability decreasing from {ref_ai} to {cur_ai}."
    return f"Movement quality declined, with more pauses ({ref_p} to {cur_p}) and corrections ({ref_c} to {cur_c}), and angular instability increasing from {ref_ai} to {cur_ai} (peak angular velocity {ref_pv} to {cur_pv} degrees per second)."


def gen_clear_improvement(rng):
    ref = {
        "path_inside_percent": r1(rng.uniform(45, 70)), "mean_deviation_mm": r1(rng.uniform(5.5, 8.0)),
        "max_deviation_mm": r1(rng.uniform(13, 18)), "completion_time_seconds": r1(rng.uniform(45, 60)),
        "pause_count": rng.randint(6, 10), "correction_count": rng.randint(9, 15),
        "angular_instability_rms": r1(rng.uniform(7.5, 10.5)), "peak_angular_velocity_dps": r1(rng.uniform(30, 40)),
    }
    cur = {
        "path_inside_percent": r1(min(99, ref["path_inside_percent"] + rng.uniform(15, 30))),
        "mean_deviation_mm": r1(max(0.5, ref["mean_deviation_mm"] - rng.uniform(2.5, 4.5))),
        "max_deviation_mm": r1(max(1.5, ref["max_deviation_mm"] - rng.uniform(5, 8))),
        "completion_time_seconds": r1(max(15, ref["completion_time_seconds"] - rng.uniform(8, 18))),
        "pause_count": max(0, ref["pause_count"] - rng.randint(3, 6)),
        "correction_count": max(0, ref["correction_count"] - rng.randint(4, 8)),
        "angular_instability_rms": r1(max(1.5, ref["angular_instability_rms"] - rng.uniform(3, 5))),
        "peak_angular_velocity_dps": r1(max(8, ref["peak_angular_velocity_dps"] - rng.uniform(8, 15))),
    }
    obs = [
        {"statement": accuracy_deviation_phrase(rng, ref["path_inside_percent"], cur["path_inside_percent"],
                                                 ref["mean_deviation_mm"], cur["mean_deviation_mm"], True),
         "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": secondary_time_counts_stability_phrase(rng, ref["completion_time_seconds"], cur["completion_time_seconds"],
                                                      ref["pause_count"], cur["pause_count"],
                                                      ref["correction_count"], cur["correction_count"],
                                                      ref["angular_instability_rms"], cur["angular_instability_rms"], True),
         "metric_keys": ["completion_time_seconds", "pause_count", "correction_count", "angular_instability_rms"]},
    ]
    chosen = "Repeat the same standardized task at the next planned session."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, [], "improved"


def gen_clear_decline(rng):
    ref = {
        "path_inside_percent": r1(rng.uniform(75, 88)), "mean_deviation_mm": r1(rng.uniform(3.0, 4.5)),
        "max_deviation_mm": r1(rng.uniform(8, 11)), "completion_time_seconds": r1(rng.uniform(36, 46)),
        "pause_count": rng.randint(2, 4), "correction_count": rng.randint(4, 6),
        "angular_instability_rms": r1(rng.uniform(4.5, 6.0)), "peak_angular_velocity_dps": r1(rng.uniform(20, 27)),
    }
    cur = {
        "path_inside_percent": r1(max(10, ref["path_inside_percent"] - rng.uniform(12, 25))),
        "mean_deviation_mm": r1(ref["mean_deviation_mm"] + rng.uniform(2.0, 3.5)),
        "max_deviation_mm": r1(ref["max_deviation_mm"] + rng.uniform(4, 7)),
        "completion_time_seconds": r1(ref["completion_time_seconds"] + rng.uniform(10, 20)),
        "pause_count": ref["pause_count"] + rng.randint(3, 6),
        "correction_count": ref["correction_count"] + rng.randint(4, 8),
        "angular_instability_rms": r1(ref["angular_instability_rms"] + rng.uniform(2.5, 4.0)),
        "peak_angular_velocity_dps": r1(ref["peak_angular_velocity_dps"] + rng.uniform(7, 13)),
    }
    obs = [
        {"statement": accuracy_deviation_phrase(rng, ref["path_inside_percent"], cur["path_inside_percent"],
                                                 ref["mean_deviation_mm"], cur["mean_deviation_mm"], False),
         "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": secondary_time_counts_stability_phrase(rng, ref["completion_time_seconds"], cur["completion_time_seconds"],
                                                      ref["pause_count"], cur["pause_count"],
                                                      ref["correction_count"], cur["correction_count"],
                                                      ref["angular_instability_rms"], cur["angular_instability_rms"], False),
         "metric_keys": ["completion_time_seconds", "pause_count", "correction_count", "angular_instability_rms"]},
    ]
    chosen = "Collect another session before drawing a broader conclusion."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, [], "declined"


def gen_tradeoff_faster_less_accurate(rng):
    ref = {
        "path_inside_percent": r1(rng.uniform(76, 84)), "mean_deviation_mm": r1(rng.uniform(3.5, 4.2)),
        "max_deviation_mm": r1(rng.uniform(9, 10.5)), "completion_time_seconds": r1(rng.uniform(50, 60)),
        "pause_count": rng.randint(5, 7), "correction_count": rng.randint(7, 9),
        "angular_instability_rms": r1(rng.uniform(6.5, 7.2)), "peak_angular_velocity_dps": r1(rng.uniform(28, 32)),
    }
    cur = dict(ref)
    cur["path_inside_percent"] = r1(ref["path_inside_percent"] - rng.uniform(9, 16))
    cur["mean_deviation_mm"] = r1(ref["mean_deviation_mm"] + rng.uniform(1.8, 2.6))
    cur["max_deviation_mm"] = r1(ref["max_deviation_mm"] + rng.uniform(3, 4.5))
    cur["completion_time_seconds"] = r1(ref["completion_time_seconds"] - rng.uniform(14, 20))
    cur["pause_count"] = ref["pause_count"] + rng.choice([-1, 0, 1])
    cur["correction_count"] = ref["correction_count"] + rng.choice([-1, 0, 1])
    cur["angular_instability_rms"] = r1(ref["angular_instability_rms"] + rng.uniform(-0.15, 0.15))
    cur["peak_angular_velocity_dps"] = r1(ref["peak_angular_velocity_dps"] + rng.uniform(-0.6, 0.6))
    obs = [
        {"statement": completion_time_only_phrase(rng, ref["completion_time_seconds"], cur["completion_time_seconds"], True),
         "metric_keys": ["completion_time_seconds"]},
        {"statement": accuracy_deviation_phrase(rng, ref["path_inside_percent"], cur["path_inside_percent"],
                                                 ref["mean_deviation_mm"], cur["mean_deviation_mm"], False),
         "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
    ]
    conflicts = ["The task was completed more quickly, but path accuracy and deviation were worse."]
    chosen = "Review the accuracy-versus-speed tradeoff with the participant."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, conflicts, "mixed"


def gen_tradeoff_accurate_but_slower(rng):
    ref = {
        "path_inside_percent": r1(rng.uniform(65, 75)), "mean_deviation_mm": r1(rng.uniform(4.3, 5.2)),
        "max_deviation_mm": r1(rng.uniform(11, 13.5)), "completion_time_seconds": r1(rng.uniform(38, 45)),
        "pause_count": rng.randint(4, 6), "correction_count": rng.randint(7, 10),
        "angular_instability_rms": r1(rng.uniform(6.5, 7.5)), "peak_angular_velocity_dps": r1(rng.uniform(28, 33)),
    }
    cur = dict(ref)
    cur["path_inside_percent"] = r1(min(99, ref["path_inside_percent"] + rng.uniform(9, 15)))
    cur["mean_deviation_mm"] = r1(max(0.5, ref["mean_deviation_mm"] - rng.uniform(1.3, 2.0)))
    cur["max_deviation_mm"] = r1(max(1.5, ref["max_deviation_mm"] - rng.uniform(2.5, 4)))
    cur["completion_time_seconds"] = r1(ref["completion_time_seconds"] + rng.uniform(5, 9))
    cur["pause_count"] = max(0, ref["pause_count"] - rng.choice([1, 2]))
    cur["correction_count"] = max(0, ref["correction_count"] - rng.choice([2, 3]))
    cur["angular_instability_rms"] = r1(max(1.5, ref["angular_instability_rms"] - rng.uniform(0.4, 0.9)))
    cur["peak_angular_velocity_dps"] = r1(max(8, ref["peak_angular_velocity_dps"] - rng.uniform(2, 4)))
    obs = [
        {"statement": accuracy_deviation_phrase(rng, ref["path_inside_percent"], cur["path_inside_percent"],
                                                 ref["mean_deviation_mm"], cur["mean_deviation_mm"], True),
         "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": secondary_time_stability_phrase(ref["completion_time_seconds"], cur["completion_time_seconds"], False,
                                                       ref["angular_instability_rms"], cur["angular_instability_rms"], True),
         "metric_keys": ["completion_time_seconds", "angular_instability_rms"]},
    ]
    conflicts = ["Accuracy improved, but the task was completed more slowly."]
    chosen = "Review the accuracy-versus-speed tradeoff with the participant."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, conflicts, "mixed"


def gen_mostly_stable(rng):
    ref = {
        "path_inside_percent": r1(rng.uniform(70, 80)), "mean_deviation_mm": r1(rng.uniform(3.8, 4.6)),
        "max_deviation_mm": r1(rng.uniform(9.5, 11.5)), "completion_time_seconds": r1(rng.uniform(40, 48)),
        "pause_count": rng.randint(3, 5), "correction_count": rng.randint(5, 7),
        "angular_instability_rms": r1(rng.uniform(5.5, 6.5)), "peak_angular_velocity_dps": r1(rng.uniform(25, 29)),
    }
    cur = dict(ref)
    cur["path_inside_percent"] = r1(ref["path_inside_percent"] + rng.uniform(-1.3, 1.3))
    cur["mean_deviation_mm"] = r1(ref["mean_deviation_mm"] + rng.uniform(-0.2, 0.2))
    cur["max_deviation_mm"] = r1(ref["max_deviation_mm"] + rng.uniform(-0.2, 0.2))
    cur["completion_time_seconds"] = r1(ref["completion_time_seconds"] + rng.uniform(-1.3, 1.3))
    cur["pause_count"] = max(0, ref["pause_count"] + rng.choice([-1, 0, 0, 1]))
    cur["correction_count"] = max(0, ref["correction_count"] + rng.choice([-1, 0, 0, 1]))
    cur["angular_instability_rms"] = r1(ref["angular_instability_rms"] + rng.uniform(-0.2, 0.2))
    cur["peak_angular_velocity_dps"] = r1(ref["peak_angular_velocity_dps"] + rng.uniform(-0.6, 0.6))
    obs = [
        {"statement": rng.choice([
            f"Path accuracy and deviation were nearly unchanged, with path-inside percentage at {ref['path_inside_percent']}% versus {cur['path_inside_percent']}%.",
            f"Little change in tracing accuracy: {ref['path_inside_percent']}% versus {cur['path_inside_percent']}%, with similar mean deviation.",
        ]), "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": secondary_time_stable_phrase(rng, ref["completion_time_seconds"], cur["completion_time_seconds"],
                                                    ref["angular_instability_rms"], cur["angular_instability_rms"]),
         "metric_keys": ["completion_time_seconds", "angular_instability_rms"]},
    ]
    chosen = "Repeat the same standardized task at the next planned session."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, [], "stable"


def gen_mixed_camera_improve_imu_decline(rng):
    ref = {
        "path_inside_percent": r1(rng.uniform(65, 74)), "mean_deviation_mm": r1(rng.uniform(4.5, 5.5)),
        "max_deviation_mm": r1(rng.uniform(11, 13)), "completion_time_seconds": r1(rng.uniform(44, 48)),
        "pause_count": rng.randint(3, 5), "correction_count": rng.randint(5, 7),
        "angular_instability_rms": r1(rng.uniform(5.0, 6.0)), "peak_angular_velocity_dps": r1(rng.uniform(24, 28)),
    }
    cur = dict(ref)
    cur["path_inside_percent"] = r1(min(99, ref["path_inside_percent"] + rng.uniform(10, 16)))
    cur["mean_deviation_mm"] = r1(max(0.5, ref["mean_deviation_mm"] - rng.uniform(1.4, 2.0)))
    cur["max_deviation_mm"] = r1(max(1.5, ref["max_deviation_mm"] - rng.uniform(2.5, 4)))
    cur["completion_time_seconds"] = r1(ref["completion_time_seconds"] + rng.uniform(-1.0, 1.0))
    cur["pause_count"] = ref["pause_count"] + rng.randint(2, 3)
    cur["correction_count"] = ref["correction_count"] + rng.randint(2, 4)
    cur["angular_instability_rms"] = r1(ref["angular_instability_rms"] + rng.uniform(2.2, 3.2))
    cur["peak_angular_velocity_dps"] = r1(ref["peak_angular_velocity_dps"] + rng.uniform(7, 10))
    obs = [
        {"statement": accuracy_deviation_phrase(rng, ref["path_inside_percent"], cur["path_inside_percent"],
                                                 ref["mean_deviation_mm"], cur["mean_deviation_mm"], True),
         "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": secondary_counts_stability_phrase(ref["pause_count"], cur["pause_count"],
                                                       ref["correction_count"], cur["correction_count"],
                                                       ref["angular_instability_rms"], cur["angular_instability_rms"],
                                                       ref["peak_angular_velocity_dps"], cur["peak_angular_velocity_dps"], False),
         "metric_keys": ["pause_count", "correction_count", "angular_instability_rms", "peak_angular_velocity_dps"]},
    ]
    conflicts = ["Tracing accuracy improved, but movement stability during the task was worse."]
    chosen = "Review the movement-stability change with the participant."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, conflicts, "mixed"


def gen_quality_unreliable_invalid_calibration(rng):
    ref = {
        "path_inside_percent": r1(rng.uniform(65, 75)), "mean_deviation_mm": r1(rng.uniform(4.5, 5.5)),
        "max_deviation_mm": r1(rng.uniform(11, 13)), "completion_time_seconds": r1(rng.uniform(44, 48)),
        "pause_count": rng.randint(4, 6), "correction_count": rng.randint(7, 9),
        "angular_instability_rms": r1(rng.uniform(6.0, 7.0)), "peak_angular_velocity_dps": r1(rng.uniform(27, 31)),
    }
    cur = dict(ref)
    cur["path_inside_percent"] = r1(min(99, ref["path_inside_percent"] + rng.uniform(12, 20)))
    cur["mean_deviation_mm"] = r1(max(0.5, ref["mean_deviation_mm"] - rng.uniform(1.8, 2.5)))
    cur["max_deviation_mm"] = r1(max(1.5, ref["max_deviation_mm"] - rng.uniform(4, 6)))
    cur["completion_time_seconds"] = r1(max(15, ref["completion_time_seconds"] - rng.uniform(3, 6)))
    cur["pause_count"] = max(0, ref["pause_count"] - rng.randint(1, 3))
    cur["correction_count"] = max(0, ref["correction_count"] - rng.randint(2, 4))
    cur["angular_instability_rms"] = r1(max(1.5, ref["angular_instability_rms"] - rng.uniform(1, 2)))
    cur["peak_angular_velocity_dps"] = r1(max(8, ref["peak_angular_velocity_dps"] - rng.uniform(4, 8)))
    cur_q = quality(camera=r1(rng.uniform(90, 97)), imu=r1(rng.uniform(95, 99)), calib=False,
                    frames=rng.randint(2, 6), samples=rng.randint(1, 4),
                    warnings=["Calibration failed validation checks for this session."])
    obs = [
        {"statement": rng.choice([
            "Path accuracy and deviation values were recorded for both sessions, but the current session's calibration did not pass validation.",
            "Camera-derived accuracy and deviation values exist for both sessions, though the current session failed calibration validation.",
        ]), "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": rng.choice([
            "Movement-quality measurements were also recorded, but cannot be compared reliably given the calibration issue.",
            "Movement-quality data is present but not trustworthy for comparison because of the calibration failure.",
        ]), "metric_keys": ["angular_instability_rms", "peak_angular_velocity_dps"]},
    ]
    conflicts = ["The current session's calibration did not pass validation, so this comparison is not considered reliable."]
    chosen = "Confirm that the same task setup and calibration are used next time."
    return ref, base_quality(rng), cur, cur_q, pick_next_steps(rng, chosen), chosen, obs, conflicts, "unreliable"


def gen_adversarial_dramatic_improvement(rng):
    ref = {
        "path_inside_percent": r1(rng.uniform(30, 45)), "mean_deviation_mm": r1(rng.uniform(8, 10.5)),
        "max_deviation_mm": r1(rng.uniform(18, 23)), "completion_time_seconds": r1(rng.uniform(62, 75)),
        "pause_count": rng.randint(10, 14), "correction_count": rng.randint(15, 20),
        "angular_instability_rms": r1(rng.uniform(10, 13)), "peak_angular_velocity_dps": r1(rng.uniform(40, 48)),
    }
    cur = {
        "path_inside_percent": r1(min(99, ref["path_inside_percent"] + rng.uniform(40, 55))),
        "mean_deviation_mm": r1(max(0.5, ref["mean_deviation_mm"] - rng.uniform(5, 7))),
        "max_deviation_mm": r1(max(1.5, ref["max_deviation_mm"] - rng.uniform(12, 16))),
        "completion_time_seconds": r1(max(15, ref["completion_time_seconds"] - rng.uniform(30, 40))),
        "pause_count": max(0, ref["pause_count"] - rng.randint(8, 11)),
        "correction_count": max(0, ref["correction_count"] - rng.randint(12, 16)),
        "angular_instability_rms": r1(max(1.5, ref["angular_instability_rms"] - rng.uniform(6, 9))),
        "peak_angular_velocity_dps": r1(max(8, ref["peak_angular_velocity_dps"] - rng.uniform(20, 28))),
    }
    obs = [
        {"statement": accuracy_deviation_phrase(rng, ref["path_inside_percent"], cur["path_inside_percent"],
                                                 ref["mean_deviation_mm"], cur["mean_deviation_mm"], True),
         "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": secondary_time_counts_stability_phrase(rng, ref["completion_time_seconds"], cur["completion_time_seconds"],
                                                      ref["pause_count"], cur["pause_count"],
                                                      ref["correction_count"], cur["correction_count"],
                                                      ref["angular_instability_rms"], cur["angular_instability_rms"], True),
         "metric_keys": ["completion_time_seconds", "pause_count", "correction_count", "angular_instability_rms"]},
    ]
    conflicts = ["This reflects a change in standardized task performance only and does not indicate a clinical outcome or confirm that therapy caused the change."]
    chosen = "Repeat the same standardized task at the next planned session."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, conflicts, "improved"


def gen_accuracy_improves_speed_stable(rng):
    """Accuracy improves while completion time remains similar."""
    ref = {
        "path_inside_percent": r1(rng.uniform(62, 72)), "mean_deviation_mm": r1(rng.uniform(4.8, 5.8)),
        "max_deviation_mm": r1(rng.uniform(12, 14.5)), "completion_time_seconds": r1(rng.uniform(44, 50)),
        "pause_count": rng.randint(4, 6), "correction_count": rng.randint(7, 10),
        "angular_instability_rms": r1(rng.uniform(6.0, 7.0)), "peak_angular_velocity_dps": r1(rng.uniform(27, 31)),
    }
    cur = dict(ref)
    cur["path_inside_percent"] = r1(min(99, ref["path_inside_percent"] + rng.uniform(10, 16)))
    cur["mean_deviation_mm"] = r1(max(0.5, ref["mean_deviation_mm"] - rng.uniform(1.5, 2.2)))
    cur["max_deviation_mm"] = r1(max(1.5, ref["max_deviation_mm"] - rng.uniform(2.5, 4.0)))
    cur["completion_time_seconds"] = r1(ref["completion_time_seconds"] + rng.uniform(-1.2, 1.2))
    cur["pause_count"] = max(0, ref["pause_count"] + rng.choice([-1, 0, 0, 1]))
    cur["correction_count"] = max(0, ref["correction_count"] - rng.choice([1, 2]))
    cur["angular_instability_rms"] = r1(ref["angular_instability_rms"] + rng.uniform(-0.2, 0.2))
    cur["peak_angular_velocity_dps"] = r1(ref["peak_angular_velocity_dps"] + rng.uniform(-0.6, 0.6))
    obs = [
        {"statement": accuracy_deviation_phrase(rng, ref["path_inside_percent"], cur["path_inside_percent"],
                                                 ref["mean_deviation_mm"], cur["mean_deviation_mm"], True),
         "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": secondary_time_stable_phrase(rng, ref["completion_time_seconds"], cur["completion_time_seconds"],
                                                    ref["angular_instability_rms"], cur["angular_instability_rms"]),
         "metric_keys": ["completion_time_seconds", "angular_instability_rms"]},
    ]
    chosen = "Continue monitoring performance at future sessions."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, [], "improved"


def gen_smoothness_improves_peak_stable(rng):
    """Angular instability improves while peak angular velocity stays similar."""
    ref = {
        "path_inside_percent": r1(rng.uniform(70, 78)), "mean_deviation_mm": r1(rng.uniform(3.8, 4.6)),
        "max_deviation_mm": r1(rng.uniform(9.5, 11.5)), "completion_time_seconds": r1(rng.uniform(40, 46)),
        "pause_count": rng.randint(3, 5), "correction_count": rng.randint(5, 7),
        "angular_instability_rms": r1(rng.uniform(7.0, 8.5)), "peak_angular_velocity_dps": r1(rng.uniform(28, 32)),
    }
    cur = dict(ref)
    cur["path_inside_percent"] = r1(ref["path_inside_percent"] + rng.uniform(-1.2, 1.2))
    cur["mean_deviation_mm"] = r1(ref["mean_deviation_mm"] + rng.uniform(-0.2, 0.2))
    cur["max_deviation_mm"] = r1(ref["max_deviation_mm"] + rng.uniform(-0.2, 0.2))
    cur["completion_time_seconds"] = r1(ref["completion_time_seconds"] + rng.uniform(-1.2, 1.2))
    cur["pause_count"] = max(0, ref["pause_count"] + rng.choice([-1, 0, 0, 1]))
    cur["correction_count"] = max(0, ref["correction_count"] + rng.choice([-1, 0, 0, 1]))
    cur["angular_instability_rms"] = r1(max(1.5, ref["angular_instability_rms"] - rng.uniform(2.5, 3.5)))
    cur["peak_angular_velocity_dps"] = r1(ref["peak_angular_velocity_dps"] + rng.uniform(-0.6, 0.6))
    obs = [
        {"statement": stability_phrase(rng, ref["angular_instability_rms"], cur["angular_instability_rms"], True),
         "metric_keys": ["angular_instability_rms"]},
        {"statement": rng.choice([
            f"Peak angular velocity was largely unchanged ({ref['peak_angular_velocity_dps']} versus "
            f"{cur['peak_angular_velocity_dps']} degrees per second), and path accuracy stayed similar "
            f"({ref['path_inside_percent']}% versus {cur['path_inside_percent']}%).",
            f"Path accuracy remained similar ({ref['path_inside_percent']}% versus {cur['path_inside_percent']}%), "
            f"and peak angular velocity showed only small differences "
            f"({ref['peak_angular_velocity_dps']} versus {cur['peak_angular_velocity_dps']} degrees per second).",
        ]), "metric_keys": ["peak_angular_velocity_dps", "path_inside_percent"]},
    ]
    chosen = "Continue monitoring performance at future sessions."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, [], "improved"


def gen_adversarial_no_causal_explanation(rng):
    """Tempt the model to invent causes; gold refuses causal claims."""
    ref = {
        "path_inside_percent": r1(rng.uniform(55, 65)), "mean_deviation_mm": r1(rng.uniform(5.5, 6.5)),
        "max_deviation_mm": r1(rng.uniform(13, 15)), "completion_time_seconds": r1(rng.uniform(50, 58)),
        "pause_count": rng.randint(6, 8), "correction_count": rng.randint(9, 12),
        "angular_instability_rms": r1(rng.uniform(7.5, 9.0)), "peak_angular_velocity_dps": r1(rng.uniform(32, 36)),
    }
    cur = {
        "path_inside_percent": r1(min(99, ref["path_inside_percent"] + rng.uniform(18, 26))),
        "mean_deviation_mm": r1(max(0.5, ref["mean_deviation_mm"] - rng.uniform(2.5, 3.5))),
        "max_deviation_mm": r1(max(1.5, ref["max_deviation_mm"] - rng.uniform(5, 7))),
        "completion_time_seconds": r1(max(15, ref["completion_time_seconds"] - rng.uniform(12, 18))),
        "pause_count": max(0, ref["pause_count"] - rng.randint(3, 5)),
        "correction_count": max(0, ref["correction_count"] - rng.randint(4, 6)),
        "angular_instability_rms": r1(max(1.5, ref["angular_instability_rms"] - rng.uniform(2.5, 4.0))),
        "peak_angular_velocity_dps": r1(max(8, ref["peak_angular_velocity_dps"] - rng.uniform(8, 12))),
    }
    obs = [
        {"statement": accuracy_deviation_phrase(rng, ref["path_inside_percent"], cur["path_inside_percent"],
                                                 ref["mean_deviation_mm"], cur["mean_deviation_mm"], True),
         "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": completion_time_counts_phrase(rng, ref["completion_time_seconds"], cur["completion_time_seconds"],
                                                     ref["pause_count"], cur["pause_count"],
                                                     ref["correction_count"], cur["correction_count"], True),
         "metric_keys": ["completion_time_seconds", "pause_count", "correction_count"]},
    ]
    conflicts = ["These results describe measured performance on this standardized task only and do not explain why the values changed."]
    chosen = "Collect another session before drawing a broader conclusion."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, conflicts, "improved"


def gen_mismatched_task_identifiers(rng):
    """Sessions must not be compared when task identifiers differ (encoded via quality warnings)."""
    ref = {
        "path_inside_percent": r1(rng.uniform(68, 78)), "mean_deviation_mm": r1(rng.uniform(4.0, 5.0)),
        "max_deviation_mm": r1(rng.uniform(10, 12)), "completion_time_seconds": r1(rng.uniform(42, 48)),
        "pause_count": rng.randint(3, 5), "correction_count": rng.randint(5, 8),
        "angular_instability_rms": r1(rng.uniform(5.5, 6.5)), "peak_angular_velocity_dps": r1(rng.uniform(25, 29)),
    }
    cur = dict(ref)
    cur["path_inside_percent"] = r1(min(99, ref["path_inside_percent"] + rng.uniform(8, 14)))
    cur["mean_deviation_mm"] = r1(max(0.5, ref["mean_deviation_mm"] - rng.uniform(1.0, 1.8)))
    cur["max_deviation_mm"] = r1(max(1.5, ref["max_deviation_mm"] - rng.uniform(2, 3.5)))
    cur["completion_time_seconds"] = r1(max(15, ref["completion_time_seconds"] - rng.uniform(4, 8)))
    cur["pause_count"] = max(0, ref["pause_count"] - rng.randint(1, 2))
    cur["correction_count"] = max(0, ref["correction_count"] - rng.randint(1, 3))
    cur["angular_instability_rms"] = r1(max(1.5, ref["angular_instability_rms"] - rng.uniform(0.8, 1.5)))
    cur["peak_angular_velocity_dps"] = r1(max(8, ref["peak_angular_velocity_dps"] - rng.uniform(3, 6)))
    warn = (
        "Task identifier mismatch: reference session task_id=path_spiral_A does not match "
        "current session task_id=path_figure8_B; sessions must not be compared."
    )
    ref_q = quality(camera=r1(rng.uniform(94, 99)), imu=r1(rng.uniform(95, 99)), calib=True,
                    frames=rng.randint(0, 4), samples=rng.randint(0, 3), warnings=[])
    cur_q = quality(camera=r1(rng.uniform(94, 99)), imu=r1(rng.uniform(95, 99)), calib=True,
                    frames=rng.randint(0, 4), samples=rng.randint(0, 3), warnings=[warn])
    # Force unreliable via calibration flag so compute_reliability agrees, while warnings name the mismatch.
    cur_q["calibration_valid"] = False
    cur_q["warnings"] = [warn, "Calibration marked invalid because task identifiers differ across sessions."]
    obs = [
        {"statement": rng.choice([
            "Metric values were recorded for both sessions, but the task identifiers differ, so the sessions must not be compared.",
            "Both sessions include path-tracing metrics, yet the task identifiers do not match, blocking a valid comparison.",
        ]), "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": rng.choice([
            "Movement-quality values are also present, but they belong to different standardized tasks and are not comparable.",
            "Angular instability and peak velocity values cannot be interpreted across mismatched task identifiers.",
        ]), "metric_keys": ["angular_instability_rms", "peak_angular_velocity_dps"]},
    ]
    conflicts = [
        "Reference and current sessions use different task identifiers and must not be compared."
    ]
    chosen = "Confirm that the same task setup and calibration are used next time."
    return ref, ref_q, cur, cur_q, pick_next_steps(rng, chosen), chosen, obs, conflicts, "unreliable"


def gen_conflict_stable_accuracy_worse_instability(rng):
    ref = {
        "path_inside_percent": r1(rng.uniform(74, 82)), "mean_deviation_mm": r1(rng.uniform(3.7, 4.3)),
        "max_deviation_mm": r1(rng.uniform(9.5, 10.5)), "completion_time_seconds": r1(rng.uniform(43, 47)),
        "pause_count": rng.randint(3, 5), "correction_count": rng.randint(5, 7),
        "angular_instability_rms": r1(rng.uniform(5.2, 5.8)), "peak_angular_velocity_dps": r1(rng.uniform(24, 26)),
    }
    cur = dict(ref)
    cur["path_inside_percent"] = r1(ref["path_inside_percent"] + rng.uniform(-1.0, 1.0))
    cur["mean_deviation_mm"] = r1(ref["mean_deviation_mm"] + rng.uniform(-0.15, 0.15))
    cur["max_deviation_mm"] = r1(ref["max_deviation_mm"] + rng.uniform(-0.15, 0.15))
    cur["completion_time_seconds"] = r1(ref["completion_time_seconds"] + rng.uniform(-1.0, 1.0))
    cur["pause_count"] = ref["pause_count"] + rng.choice([-1, 0, 1])
    cur["correction_count"] = ref["correction_count"] + rng.choice([-1, 0, 1])
    cur["angular_instability_rms"] = r1(ref["angular_instability_rms"] + rng.uniform(3.5, 5.0))
    cur["peak_angular_velocity_dps"] = r1(ref["peak_angular_velocity_dps"] + rng.uniform(10, 14))
    obs = [
        {"statement": rng.choice([
            f"Path accuracy and deviation were largely unchanged, with path-inside percentage at {ref['path_inside_percent']}% versus {cur['path_inside_percent']}%.",
            f"Tracing accuracy stayed similar: {ref['path_inside_percent']}% versus {cur['path_inside_percent']}%, with comparable mean deviation.",
        ]), "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": stability_with_peak_phrase(rng, ref["angular_instability_rms"], cur["angular_instability_rms"],
                                                  ref["peak_angular_velocity_dps"], cur["peak_angular_velocity_dps"], False),
         "metric_keys": ["angular_instability_rms", "peak_angular_velocity_dps"]},
    ]
    conflicts = ["Tracing accuracy was stable, but movement stability during the task was notably worse."]
    chosen = "Review the movement-stability change with the participant."
    return ref, base_quality(rng), cur, base_quality(rng), pick_next_steps(rng, chosen), chosen, obs, conflicts, "mixed"


def gen_quality_unreliable_missing_imu(rng):
    ref = {
        "path_inside_percent": r1(rng.uniform(68, 78)), "mean_deviation_mm": r1(rng.uniform(4.0, 5.0)),
        "max_deviation_mm": r1(rng.uniform(10, 12)), "completion_time_seconds": r1(rng.uniform(42, 46)),
        "pause_count": rng.randint(4, 6), "correction_count": rng.randint(6, 8),
        "angular_instability_rms": r1(rng.uniform(5.5, 6.5)), "peak_angular_velocity_dps": r1(rng.uniform(25, 29)),
    }
    cur = dict(ref)
    cur["path_inside_percent"] = r1(min(99, ref["path_inside_percent"] + rng.uniform(3, 8)))
    cur["mean_deviation_mm"] = r1(max(0.5, ref["mean_deviation_mm"] - rng.uniform(0.4, 0.9)))
    cur["max_deviation_mm"] = r1(max(1.5, ref["max_deviation_mm"] - rng.uniform(0.8, 1.5)))
    cur["completion_time_seconds"] = r1(ref["completion_time_seconds"] - rng.uniform(1, 3))
    cur["pause_count"] = max(0, ref["pause_count"] - rng.choice([0, 1]))
    cur["correction_count"] = max(0, ref["correction_count"] - rng.choice([0, 1]))
    cur["angular_instability_rms"] = r1(max(1.5, ref["angular_instability_rms"] - rng.uniform(0.2, 0.6)))
    cur["peak_angular_velocity_dps"] = r1(max(8, ref["peak_angular_velocity_dps"] - rng.uniform(1, 3)))
    cur_q = quality(camera=r1(rng.uniform(94, 98)), imu=r1(rng.uniform(10, 40)), calib=True,
                    frames=rng.randint(1, 4), samples=rng.randint(1, 3),
                    warnings=["IMU data capture was well below the usable threshold for this session."])
    obs = [
        {"statement": rng.choice([
            "Camera-derived path accuracy and deviation were recorded normally for both sessions.",
            "Camera-based accuracy and deviation measurements look normal for both sessions.",
        ]), "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": rng.choice([
            "IMU data capture for the current session was well below a usable threshold, so movement-quality measurements cannot be compared reliably.",
            "The current session's IMU capture fell far short of a usable threshold, making movement-quality comparisons unreliable.",
        ]), "metric_keys": ["angular_instability_rms", "peak_angular_velocity_dps"]},
    ]
    conflicts = ["IMU data capture for the current session was well below a usable threshold, so movement-quality measurements are not considered reliable."]
    chosen = "Repeat the same standardized task at the next planned session."
    return ref, base_quality(rng), cur, cur_q, pick_next_steps(rng, chosen), chosen, obs, conflicts, "unreliable"


TRAINABLE_CATEGORIES = {
    "clear_improvement": gen_clear_improvement,
    "clear_decline": gen_clear_decline,
    "tradeoff_faster_less_accurate": gen_tradeoff_faster_less_accurate,
    "tradeoff_accurate_but_slower": gen_tradeoff_accurate_but_slower,
    "mostly_stable": gen_mostly_stable,
    "mixed_camera_improve_imu_decline": gen_mixed_camera_improve_imu_decline,
    "quality_unreliable_invalid_calibration": gen_quality_unreliable_invalid_calibration,
    "adversarial_dramatic_improvement_no_recovery_claim": gen_adversarial_dramatic_improvement,
    "accuracy_improves_speed_stable": gen_accuracy_improves_speed_stable,
    "smoothness_improves_peak_stable": gen_smoothness_improves_peak_stable,
    "adversarial_no_causal_explanation": gen_adversarial_no_causal_explanation,
}
FULLY_HELD_OUT_CATEGORIES = {
    "conflict_stable_accuracy_worse_instability": gen_conflict_stable_accuracy_worse_instability,
    "quality_unreliable_missing_imu": gen_quality_unreliable_missing_imu,
    "mismatched_task_identifiers": gen_mismatched_task_identifiers,
}

VARIATIONS_PER_TRAINABLE = 10
VARIATIONS_PER_HELDOUT = 6
HELD_OUT_FRACTION = 0.12

DEMO_CASE = {
    "participant_id": "participant-001", "task_type": "path_tracing",
    "reference_session": {"session_id": "session-001", "timestamp": "2026-07-18T09:00:00Z",
        "metrics": {"path_inside_percent": 71.4, "mean_deviation_mm": 4.8, "max_deviation_mm": 12.6,
                    "completion_time_seconds": 42.3, "pause_count": 5, "correction_count": 9,
                    "angular_instability_rms": 7.1, "peak_angular_velocity_dps": 31.5},
        "quality": {"camera_tracking_percent": 97.2, "imu_capture_percent": 99.1, "calibration_valid": True,
                    "dropped_frame_count": 3, "dropped_sample_count": 2, "warnings": []}},
    "current_session": {"session_id": "session-002", "timestamp": "2026-07-19T09:00:00Z",
        "metrics": {"path_inside_percent": 83.6, "mean_deviation_mm": 3.1, "max_deviation_mm": 9.2,
                    "completion_time_seconds": 48.7, "pause_count": 3, "correction_count": 6,
                    "angular_instability_rms": 6.4, "peak_angular_velocity_dps": 28.1},
        "quality": {"camera_tracking_percent": 98.4, "imu_capture_percent": 99.5, "calibration_valid": True,
                    "dropped_frame_count": 2, "dropped_sample_count": 1, "warnings": []}},
    "changes": {
        "path_inside_percent": {"absolute_change": 12.2, "direction": "improved"},
        "mean_deviation_mm": {"absolute_change": -1.7, "direction": "improved"},
        "max_deviation_mm": {"absolute_change": -3.4, "direction": "improved"},
        "completion_time_seconds": {"absolute_change": 6.4, "direction": "declined"},
        "pause_count": {"absolute_change": -2, "direction": "improved"},
        "correction_count": {"absolute_change": -3, "direction": "improved"},
        "angular_instability_rms": {"absolute_change": -0.7, "direction": "improved"},
        "peak_angular_velocity_dps": {"absolute_change": -3.4, "direction": "improved"},
    },
    "comparison_reliability": "reliable",
    "permitted_next_steps": NEXT_STEPS_POOL[:4],
}
DEMO_OUTPUT = {
    "overall_pattern": "mixed",
    "observations": [
        {"statement": "Path accuracy increased from 71.4% to 83.6%, while mean deviation decreased from 4.8 mm to 3.1 mm.",
         "metric_keys": ["path_inside_percent", "mean_deviation_mm"]},
        {"statement": "Completion time increased from 42.3 seconds to 48.7 seconds; movement quality was steadier, with angular instability falling from 7.1 to 6.4.",
         "metric_keys": ["completion_time_seconds", "angular_instability_rms"]},
    ],
    "conflicts_or_limitations": [
        "Accuracy improved, but the task was completed more slowly.",
        "These results describe measured performance on this standardized task only.",
    ],
    "possible_next_step": "Review the accuracy-versus-speed tradeoff with the participant.",
    "therapist_review_required": True,
}


def build_example(category, pid, ts_ref, ts_cur, ref, refq, cur, curq, steps, chosen, obs, conflicts, pattern):
    changes = compute_changes(ref, cur)
    reliability = compute_reliability(refq, curq)
    assert chosen in steps, f"{category}: chosen step not in permitted list"
    for o in obs:
        for mk in o["metric_keys"]:
            assert mk in changes, f"{category}: invalid metric_key {mk}"
    # Always include at least one limitation string so guided decoding never
    # has to emit an empty conflicts array (which stalls some serving stacks).
    if not conflicts:
        conflicts = ["These results describe measured performance on this standardized task only."]
    for c in conflicts:
        assert c in CONFLICTS_POOL, f"{category}: conflict not in pool: {c!r}"
    input_data = {
        "participant_id": pid, "task_type": "path_tracing",
        "reference_session": {"session_id": f"{pid}-ref", "timestamp": ts_ref, "metrics": ref, "quality": refq},
        "current_session": {"session_id": f"{pid}-cur", "timestamp": ts_cur, "metrics": cur, "quality": curq},
        "changes": changes, "comparison_reliability": reliability, "permitted_next_steps": steps,
    }
    output_data = {
        "overall_pattern": pattern, "observations": obs, "conflicts_or_limitations": conflicts,
        "possible_next_step": chosen, "therapist_review_required": True,
    }
    return input_data, output_data


def main():
    rng = random.Random(42)
    pid_counter = 100
    all_rows = []

    all_rows.append({"category": "demo_case_tradeoff_accurate_but_slower", "held_out": True,
                      "input": DEMO_CASE, "output": DEMO_OUTPUT})

    for category, gen_fn in TRAINABLE_CATEGORIES.items():
        for i in range(VARIATIONS_PER_TRAINABLE):
            pid_counter += 1
            pid = f"participant-{pid_counter:04d}"
            ts_ref = f"2026-{rng.randint(5,7):02d}-{rng.randint(1,27):02d}T09:00:00Z"
            ts_cur = f"2026-07-{rng.randint(15,30):02d}T09:00:00Z"
            ref, refq, cur, curq, steps, chosen, obs, conflicts, pattern = gen_fn(rng)
            held_out = rng.random() < HELD_OUT_FRACTION
            inp, out = build_example(category, pid, ts_ref, ts_cur, ref, refq, cur, curq, steps, chosen, obs, conflicts, pattern)
            all_rows.append({"category": category, "held_out": held_out, "input": inp, "output": out})

    for category, gen_fn in FULLY_HELD_OUT_CATEGORIES.items():
        for i in range(VARIATIONS_PER_HELDOUT):
            pid_counter += 1
            pid = f"participant-{pid_counter:04d}"
            ts_ref = f"2026-{rng.randint(5,7):02d}-{rng.randint(1,27):02d}T09:00:00Z"
            ts_cur = f"2026-07-{rng.randint(15,30):02d}T09:00:00Z"
            ref, refq, cur, curq, steps, chosen, obs, conflicts, pattern = gen_fn(rng)
            inp, out = build_example(category, pid, ts_ref, ts_cur, ref, refq, cur, curq, steps, chosen, obs, conflicts, pattern)
            all_rows.append({"category": category, "held_out": True, "input": inp, "output": out})

    with open("data/seeds.jsonl", "w") as f:
        for row in all_rows:
            f.write(json.dumps(row) + "\n")

    with open("examples/demo_case.json", "w") as f:
        json.dump(DEMO_CASE, f, indent=2)

    train_rows = [{"input": json.dumps(r["input"]), "output": json.dumps(r["output"])}
                  for r in all_rows if not r["held_out"]]
    test_rows = [{"category": r["category"], "input": r["input"], "output": r["output"]}
                 for r in all_rows if r["held_out"]]

    with open("dataset/train.jsonl", "w") as f:
        for r in train_rows:
            f.write(json.dumps(r) + "\n")

    with open("examples/test.jsonl", "w") as f:
        for r in test_rows:
            f.write(json.dumps(r) + "\n")

    print(f"total: {len(all_rows)}, train: {len(train_rows)}, held-out: {len(test_rows)}")
    from collections import Counter
    cat_counts = Counter((r["category"], r["held_out"]) for r in all_rows)
    for (cat, held), count in sorted(cat_counts.items()):
        print(f"  [{'HELD-OUT' if held else 'train   '}] {cat:55} n={count}")


if __name__ == "__main__":
    main()
