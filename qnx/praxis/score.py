"""Praxis deterministic scoring — the single source of truth for the global
0-100 accuracy and stability scales and their performance bands.

This module is intentionally dependency-free and platform-independent so the
EXACT same definitions can be used by the QNX server, the saved session bundle,
and (by porting these constants/formulas) the external web app. The LLM layer
never touches any of this.

Version the scale: any change to a formula, tolerance or band boundary MUST bump
SCORE_VERSION so stored sessions remain interpretable.
"""
import math

SCORE_VERSION = "praxis-score-1.0.0"

# --- Accuracy: spatial error + coverage -----------------------------------
# position = 100 * exp(-mean_perpendicular_deviation_mm / ACC_TOL_MM)
# accuracy = position * (coverage_pct / 100)
# ACC_TOL_MM is the mean deviation at the ~37/100 position point.
ACC_TOL_MM = 5.0

# --- Stability: high-frequency tool oscillation (tremor) ------------------
# stability = 100 * exp(-tremor_rms_deg_s / STAB_TOL_DPS)
# tremor_rms is the timestamp-aware residual after removing intended motion
# (computed upstream from the IMU stream).
STAB_TOL_DPS = 6.0

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


def accuracy_score(mean_dev_mm, coverage_pct):
    """0-100 accuracy from mean perpendicular deviation (mm) and coverage (%).
    Returns None if inputs are missing (never fabricate)."""
    if mean_dev_mm is None or coverage_pct is None:
        return None
    position = 100.0 * math.exp(-max(0.0, mean_dev_mm) / ACC_TOL_MM)
    return round(_clamp(position * (coverage_pct / 100.0)), 1)


def stability_score(tremor_rms_deg_s):
    """0-100 stability from high-frequency tremor RMS (deg/s). None if missing."""
    if tremor_rms_deg_s is None:
        return None
    return round(_clamp(100.0 * math.exp(-max(0.0, tremor_rms_deg_s) / STAB_TOL_DPS)), 1)


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
            "formula": "100*exp(-mean_dev_mm/ACC_TOL_MM)*(coverage_pct/100)",
            "ACC_TOL_MM": ACC_TOL_MM,
        },
        "stability": {
            "inputs": ["tremor_rms_deg_s"],
            "formula": "100*exp(-tremor_rms_deg_s/STAB_TOL_DPS)",
            "STAB_TOL_DPS": STAB_TOL_DPS,
        },
        "bands": [{"lo": lo, "hi": hi, "name": name} for lo, hi, name in BANDS],
    }
