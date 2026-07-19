#!/usr/bin/env python3
"""Run the trained image-quality model. QNX stdlib only."""
import argparse
import json
import time

from features import extract_features, probability


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    try:
        with open(args.model) as source:
            model = json.load(source)
        valid_probability = probability(model, extract_features(args.image))
        valid = valid_probability >= model["threshold"]
        result = {
            "ok": True,
            "model_version": model["model_version"],
            "classification": "valid" if valid else "invalid",
            "valid_probability": round(valid_probability, 4),
            "repeat_recommended": not valid,
            "threshold": model["threshold"],
            "inference_ms": round((time.monotonic() - started) * 1000, 1),
        }
    except Exception as error:
        result = {"ok": False, "error": str(error),
                  "inference_ms": round((time.monotonic() - started) * 1000, 1)}
    print(json.dumps(result))


if __name__ == "__main__":
    main()

