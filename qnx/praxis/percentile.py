"""Praxis percentile ranks — computed ONLY from a real, versioned reference
distribution of comparable runs, stratified by task type/version/difficulty.

A score is not a percentile. If no valid reference stratum exists (or it is too
small), the percentile is null and the UI/summary must say "Percentile
unavailable" — never fabricate one. Prototype reference sets are labeled as such.
"""
import glob
import json
import os

# A stratum needs at least this many samples to yield a valid percentile.
MIN_REFERENCE_N = 20

_REF_DIR = os.path.join(os.path.dirname(__file__), "reference_sets")


def _load_all(ref_dir=None):
    ref_dir = ref_dir or _REF_DIR
    sets = []
    for path in sorted(glob.glob(os.path.join(ref_dir, "*.json"))):
        try:
            with open(path) as f:
                sets.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    return sets


def _find_stratum(task, ref_dir=None):
    """Return (refset, stratum) matching task type/version/difficulty, or (None,None).
    Picks the highest-priority set that has a matching stratum (non-prototype
    preferred over prototype)."""
    tt = task.get("type")
    tv = task.get("version")
    td = task.get("difficulty")
    candidates = _load_all(ref_dir)
    # non-prototype first, then prototype
    candidates.sort(key=lambda s: (bool(s.get("is_prototype")),))
    for refset in candidates:
        for stratum in refset.get("strata", []):
            if (stratum.get("task_type") == tt and
                    stratum.get("task_version") == tv and
                    (td is None or stratum.get("difficulty") == td)):
                return refset, stratum
    return None, None


def _rank(value, samples):
    """Percentile rank: percentage of reference samples <= value (0-100)."""
    if not samples:
        return None
    below = sum(1 for s in samples if s <= value)
    return round(100.0 * below / len(samples), 1)


def percentile_for(measure, score, task, ref_dir=None):
    """Percentile metadata for one measure ('accuracy'|'stability').

    Always returns a dict; percentile is null when no valid reference exists."""
    base = {
        "measure": measure,
        "percentile": None,
        "reference_set_version": None,
        "sample_count": 0,
        "population": None,
        "is_prototype": None,
        "label": "Percentile unavailable",
    }
    if score is None:
        return base
    refset, stratum = _find_stratum(task, ref_dir)
    if not stratum:
        return base
    samples = stratum.get(measure) or []
    if len(samples) < MIN_REFERENCE_N:
        # a stratum exists but is too small to be a valid distribution
        base["reference_set_version"] = refset.get("refset_version")
        base["sample_count"] = len(samples)
        return base
    is_proto = bool(refset.get("is_prototype"))
    pct = _rank(score, samples)
    return {
        "measure": measure,
        "percentile": pct,
        "reference_set_version": refset.get("refset_version"),
        "sample_count": len(samples),
        "population": refset.get("population"),
        "is_prototype": is_proto,
        "label": ("prototype reference-set percentile" if is_proto
                  else "reference-set percentile"),
    }


def compute_percentiles(accuracy, stability, task, ref_dir=None):
    """Percentile metadata for both measures."""
    return {
        "accuracy": percentile_for("accuracy", accuracy, task, ref_dir),
        "stability": percentile_for("stability", stability, task, ref_dir),
    }
