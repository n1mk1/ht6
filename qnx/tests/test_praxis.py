"""Platform-independent tests for the Praxis deterministic layer.
Run on any host: python3 qnx/tests/test_praxis.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from praxis import score, percentile, explain  # noqa: E402

FAIL = 0


def check(cond, msg):
    global FAIL
    if not cond:
        print(f"  FAIL: {msg}")
        FAIL += 1


# ---- scoring boundaries --------------------------------------------------
def test_scores():
    # perfect trace: 0 mm deviation, full coverage -> 100
    check(score.accuracy_score(0.0, 100.0) == 100.0, "acc perfect == 100")
    # coverage is a quality gate, not a score multiplier
    check(score.accuracy_score(0.0, 59.9) is None,
          "acc below minimum coverage -> None")
    check(score.accuracy_score(0.0, 60.0) == 100.0,
          "acc at minimum coverage uses deviation score")
    # missing inputs -> None (never fabricate)
    check(score.accuracy_score(None, 100.0) is None, "acc None input -> None")
    check(score.accuracy_score(0.0, None) is None, "acc missing coverage -> None")
    check(score.stability_score(None) is None, "stab None -> None")
    # stability: 0 tremor -> 100, monotonic decrease
    check(score.stability_score(0.0) == 100.0, "stab perfect == 100")
    check(score.stability_score(6.0) < score.stability_score(3.0), "stab monotonic")
    # baseline anchors
    check(score.accuracy_score(score.ACC_GOOD_MM, 72.4) == 90.0, "good acc anchor -> 90")
    check(score.accuracy_score(score.ACC_BAD_MM, 100.0) == 10.0, "bad acc anchor -> 10")
    check(score.stability_score(score.STAB_GOOD_DPS) == 90.0, "good stab anchor -> 90")
    check(score.stability_score(score.STAB_BAD_DPS) == 10.0, "bad stab anchor -> 10")


# ---- band boundaries -----------------------------------------------------
def test_bands():
    check(score.band(0) == "very low", "0 -> very low")
    check(score.band(19.9) == "very low", "19.9 -> very low")
    check(score.band(20) == "low", "20 -> low")
    check(score.band(59.9) == "moderate", "59.9 -> moderate")
    check(score.band(60) == "high", "60 -> high")
    check(score.band(80) == "very high", "80 -> very high")
    check(score.band(100) == "very high", "100 -> very high")
    check(score.band(None) == "unknown", "None -> unknown")


# ---- percentile calculation ----------------------------------------------
def test_percentile_valid():
    task = {"type": "path_tracing", "version": "mat_v1", "difficulty": 1}
    r = percentile.percentile_for("accuracy", 50.2, task)
    check(r["percentile"] is not None, "valid stratum -> numeric percentile")
    check(0 <= r["percentile"] <= 100, "percentile in range")
    check(r["is_prototype"] is True, "proto set flagged prototype")
    check(r["label"] == "prototype reference-set percentile", "prototype label")
    check(r["sample_count"] == 30, "sample count recorded")
    # lowest possible score -> low percentile; highest -> high percentile
    lo = percentile.percentile_for("accuracy", 0.0, task)["percentile"]
    hi = percentile.percentile_for("accuracy", 100.0, task)["percentile"]
    check(lo < hi, "percentile monotonic")


def test_percentile_missing():
    # no matching stratum -> null + "Percentile unavailable"
    task = {"type": "unknown_task", "version": "zzz", "difficulty": 9}
    r = percentile.percentile_for("accuracy", 50.0, task)
    check(r["percentile"] is None, "no stratum -> null percentile")
    check(r["label"] == "Percentile unavailable", "unavailable label")
    # None score -> null
    task2 = {"type": "path_tracing", "version": "mat_v1", "difficulty": 1}
    r2 = percentile.percentile_for("accuracy", None, task2)
    check(r2["percentile"] is None, "None score -> null percentile")


# ---- LLM validation + fallback -------------------------------------------
def _sample_obj():
    task = {"type": "path_tracing", "version": "mat_v1", "difficulty": 1}
    scores = {"accuracy": 26.4, "stability": 43.4}
    bands = {"accuracy": score.band(26.4), "stability": score.band(43.4)}
    pcts = percentile.compute_percentiles(26.4, 43.4, task)
    metrics = {"coverage_pct": 100.0, "mean_dev_mm": 6.8,
               "completion_time_seconds": 12.3, "gyro_rms_deg_s": 8.1,
               "tremor_rms_deg_s": 5.0}
    return explain.build_input(task, scores, bands, pcts, metrics, [])


def test_llm_validation():
    obj = _sample_obj()
    # faithful summary (uses only source numbers + exact scores/bands) -> valid
    good = ("Accuracy scored 26.4 (low) and stability scored 43.4 (moderate). "
            "Mean spatial error was 6.8 mm with 100.0% coverage. "
            + explain.DISCLAIMER)
    check(explain.validate_summary(good, obj), "faithful summary validates")
    # fabricated number (99) -> rejected
    bad = ("Accuracy scored 26.4 (low) and stability scored 43.4 (moderate), "
           "which is 99 percent better than average.")
    check(not explain.validate_summary(bad, obj), "fabricated number rejected")
    # altered score -> rejected (missing exact score string)
    bad2 = "Accuracy scored 30.0 (low) and stability scored 43.4 (moderate)."
    check(not explain.validate_summary(bad2, obj), "altered score rejected")
    bad3 = (explain._score_sentence(obj) +
            " Both measurements were at the 100th percentile. " +
            explain.DISCLAIMER)
    check(not explain.validate_summary(bad3, obj),
          "generic scale bound cannot hide a fabricated percentile")


def test_explain_fallback():
    obj = _sample_obj()
    # llama not configured -> deterministic template, always valid
    r = explain.explain(obj)
    check(r["source"] == "template", "no llama -> template source")
    check(r["validated"] is True, "template is validated")
    check("26.4" in r["summary"] and "43.4" in r["summary"], "scores repeated")
    check("prototype" in r["summary"].lower() or
          "Percentile unavailable" in r["summary"], "caveat/percentile present")
    # template must itself pass validation (no stray numbers)
    check(explain.validate_summary(r["summary"], obj), "template self-validates")


def test_generated_summary_contract():
    obj = _sample_obj()
    generated = (explain._score_sentence(obj) + " Mean spatial error was 6.8 mm. "
                 + explain.DISCLAIMER)
    check(explain.validate_summary(generated, obj),
          "grounded generated summary validates")
    check(not explain.validate_summary(generated.replace(explain.DISCLAIMER, ""), obj),
          "generated summary without limitation is rejected")
    check(not explain.validate_summary(generated.replace("6.8", "7.7"), obj),
          "generated summary with invented metric is rejected")
    check(explain._validate_analysis(
        "Mean spatial error was 6.8 mm with 100.0% pattern coverage, and "
        "completion time was 12.3 s.", obj),
        "neutral generated analysis validates")
    check(not explain._validate_analysis(
        "Mean spatial error was within acceptable limits at 6.8 mm.", obj),
        "unsupported qualitative threshold is rejected")
    check(not explain._validate_analysis(
        "Mean spatial error was 6.8 mm, indicating slight patient movement.", obj),
        "unsupported generated inference is rejected")


# ---- structured-input schema ---------------------------------------------
def test_input_schema():
    obj = _sample_obj()
    for k in ("task", "scores", "bands", "percentiles", "metrics",
              "quality_warnings"):
        check(k in obj, f"input has '{k}'")
    for k in ("coverage_pct", "mean_dev_mm", "completion_time_seconds",
              "tremor_rms_deg_s"):
        check(k in obj["metrics"], f"metrics has '{k}'")


if __name__ == "__main__":
    print("running Praxis tests...")
    for fn in (test_scores, test_bands, test_percentile_valid,
               test_percentile_missing, test_llm_validation,
               test_explain_fallback, test_generated_summary_contract,
               test_input_schema):
        fn()
    if FAIL == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"{FAIL} CHECK(S) FAILED")
    sys.exit(1 if FAIL else 0)
