"""Regression tests for the dependency-free image-quality model.

The captured images are intentionally gitignored. Model-contract tests always
run; dataset regression checks run when the local captures are present.
"""
import csv
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from image_quality.features import (FEATURE_COUNT, FEATURE_VERSION,
                                    extract_features, mirror_features,
                                    probability)  # noqa: E402

MODEL_PATH = os.path.join(ROOT, "image_quality", "model", "quality_model.json")
DATASET = os.path.join(ROOT, "datasets", "image_quality", "data")
FAIL = 0


def check(condition, message):
    global FAIL
    if not condition:
        print(f"  FAIL: {message}")
        FAIL += 1


def load_model():
    with open(MODEL_PATH) as source:
        return json.load(source)


def test_model_contract():
    model = load_model()
    check(model["model_version"] == "praxis-image-quality-1.0.0",
          "expected model version")
    check(model["feature_version"] == FEATURE_VERSION,
          "model and extractor feature versions agree")
    for key in ("means", "scales", "weights"):
        check(len(model[key]) == FEATURE_COUNT, f"{key} has expected shape")
    check(all(scale > 0 for scale in model["scales"]),
          "all normalization scales are positive")
    check(0 < model["threshold"] < 1, "threshold is a probability")
    training = model["training"]
    check(training["samples"] == 30, "training provenance records 30 images")
    check(training["valid_samples"] == 10, "training provenance records 10 valid")
    check(training["invalid_samples"] == 20, "training provenance records 20 invalid")


def test_dataset_regression():
    labels_path = os.path.join(DATASET, "labels.csv")
    if not os.path.isfile(labels_path):
        print("  SKIP: captured dataset is not present")
        return
    model = load_model()
    rows = list(csv.DictReader(open(labels_path, newline="")))
    check(len(rows) == 30, "dataset contains 30 labels")
    correct = 0
    for row in rows:
        path = os.path.join(DATASET, row["filename"])
        check(os.path.isfile(path), f"capture {row['shot_id']} exists")
        if not os.path.isfile(path):
            continue
        features = extract_features(path)
        check(len(features) == FEATURE_COUNT,
              f"capture {row['shot_id']} has the expected feature count")
        score = probability(model, features)
        check(0 <= score <= 1, f"capture {row['shot_id']} probability is bounded")
        predicted = "valid" if score >= model["threshold"] else "invalid"
        correct += predicted == row["label"]
    check(correct == len(rows), "final model reproduces all training labels")


def test_mirror_contract():
    labels_path = os.path.join(DATASET, "labels.csv")
    if not os.path.isfile(labels_path):
        return
    row = next(csv.DictReader(open(labels_path, newline="")))
    features = extract_features(os.path.join(DATASET, row["filename"]))
    mirrored = mirror_features(features)
    check(len(mirrored) == FEATURE_COUNT, "mirroring preserves model shape")
    check(mirror_features(mirrored) == features, "mirroring twice restores features")


if __name__ == "__main__":
    print("running image-quality tests...")
    test_model_contract()
    test_dataset_regression()
    test_mirror_contract()
    if FAIL == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"{FAIL} CHECK(S) FAILED")
    sys.exit(1 if FAIL else 0)
