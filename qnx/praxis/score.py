"""Praxis deterministic scoring — the single source of truth for the global
0-100 accuracy and stability scales and their performance bands.

This module is intentionally dependency-free and platform-independent so the
EXACT same definitions can be used by the QNX server, the saved session bundle,
and (by porting these constants/formulas) the external web app. The LLM layer
never touches any of this.

Version the scale: any change to a formula, tolerance or band boundary MUST bump
SCORE_VERSION so stored sessions remain interpretable.
"""
SCORE_VERSION = "praxis-score-1.2.0"

# --- Accuracy: spatial error + coverage -----------------------------------
# Calibrated from two QNX baseline runs on the fixed mat/camera setup:
#   KatieCalibrationGood: mean_dev_mm=1.86 -> score 90
#   katiecalibrationbad:  mean_dev_mm=13.04 -> score 10
# Coverage remains a quality metric; it is not used as a multiplier because the
# good anchor had only 72.4% detected coverage despite a visually accurate trace.
ACC_GOOD_MM = 1.86
ACC_BAD_MM = 13.04
# Below this coverage, the observed fragment is not representative enough to
# assign an accuracy score. Raw deviation and coverage remain in the session.
MIN_ACCURACY_COVERAGE_PCT = 60.0

# --- Stability: high-frequency tool oscillation (tremor) ------------------
# Calibrated from the same baseline runs:
#   KatieCalibrationGood: tremor_rms_deg_s=5.18 -> score 90
#   katiecalibrationbad:  tremor_rms_deg_s=35.91 -> score 10
STAB_GOOD_DPS = 5.18
STAB_BAD_DPS = 35.91

# --- Performance bands on the 0-100 score ---------------------------------
# [lo, hi) half-open, top band closed at 100. Deterministic, versioned.
BANDS = [
    (0.0, 20.0, "very low"),
    (20.0, 40.0, "low"),
    (40.0, 60.0, "moderate"),
    (60.0, 80.0, "high"),
    (80.0, 100.0, "very high"),
]


def _clamp(x, lo=0.0, hi=100.0):
    return lo if x < lo else hi if x > hi else x


def _anchor_score(value, good_value, bad_value):
    """Lower-is-better anchor scale: good baseline -> 90, bad baseline -> 10."""
    span = bad_value - good_value
    if span <= 0:
        return None
    score = 90.0 - ((max(0.0, value) - good_value) * (80.0 / span))
    return round(_clamp(score), 1)


def accuracy_score(mean_dev_mm, coverage_pct):
    """0-100 accuracy from mean perpendicular deviation (mm).
    Returns None if inputs are missing (never fabricate)."""
    if mean_dev_mm is None or coverage_pct is None:
        return None
    if coverage_pct < MIN_ACCURACY_COVERAGE_PCT:
        return None
    return _anchor_score(mean_dev_mm, ACC_GOOD_MM, ACC_BAD_MM)


def stability_score(tremor_rms_deg_s):
    """0-100 stability from high-frequency tremor RMS (deg/s). None if missing."""
    if tremor_rms_deg_s is None:
        return None
    return _anchor_score(tremor_rms_deg_s, STAB_GOOD_DPS, STAB_BAD_DPS)


def band(score):
    """Named performance band for a 0-100 score. 'unknown' if score is None."""
    if score is None:
        return "unknown"
    s = _clamp(score)
    for lo, hi, name in BANDS:
        if lo <= s < hi:
            return name
    return BANDS[-1][2]  # exactly 100 -> top band


def score_definitions():
    """Machine-readable description of the scale, stored in every session so a
    result is always interpretable against the version that produced it."""
    return {
        "version": SCORE_VERSION,
        "accuracy": {
            "inputs": ["mean_dev_mm", "coverage_pct"],
            "formula": "linear lower-is-better anchor scale: good->90, bad->10",
            "coverage_role": "quality metric only; not a score multiplier",
            "minimum_coverage_pct": MIN_ACCURACY_COVERAGE_PCT,
            "ACC_GOOD_MM": ACC_GOOD_MM,
            "ACC_BAD_MM": ACC_BAD_MM,
            "good_anchor": "KatieCalibrationGood session_015856",
            "bad_anchor": "katiecalibrationbad session_021311",
        },
        "stability": {
            "inputs": ["tremor_rms_deg_s"],
            "formula": "linear lower-is-better anchor scale: good->90, bad->10",
            "STAB_GOOD_DPS": STAB_GOOD_DPS,
            "STAB_BAD_DPS": STAB_BAD_DPS,
            "good_anchor": "KatieCalibrationGood session_015856",
            "bad_anchor": "katiecalibrationbad session_021311",
        },
        "bands": [{"lo": lo, "hi": hi, "name": name} for lo, hi, name in BANDS],
    }
