"""Run on the QNX Pi to verify real llama.cpp summary generation."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from praxis import explain, percentile, score  # noqa: E402


def main():
    task = {"type": "path_tracing", "version": "mat_v1", "difficulty": 1,
            "hand": "right"}
    scores = {"accuracy": 90.0, "stability": 90.0}
    bands = {name: score.band(value) for name, value in scores.items()}
    metrics = {"coverage_pct": 98.4, "mean_dev_mm": 1.1,
               "completion_time_seconds": 14.2, "gyro_rms_deg_s": 3.4,
               "tremor_rms_deg_s": 0.7}
    image_quality = {"ok": True, "classification": "valid",
                     "valid_probability": 0.97, "threshold": 0.5,
                     "inference_ms": 460.0}
    obj = explain.build_input(
        task, scores, bands,
        percentile.compute_percentiles(90.0, 90.0, task), metrics, [],
        image_quality)
    summary = explain._run_llama(obj)
    print(json.dumps({"summary": summary, "validated":
                      explain.validate_summary(summary, obj)}, indent=2))
    if not explain.validate_summary(summary, obj):
        raise SystemExit("generated summary did not pass validation")


if __name__ == "__main__":
    main()
