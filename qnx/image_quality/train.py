#!/usr/bin/env python3
"""Train the small binary image-quality model from labeled camera BMPs."""
import argparse
import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone

from features import (FEATURE_COUNT, FEATURE_VERSION, extract_features,
                      mirror_features, probability)


MODEL_VERSION = "praxis-image-quality-1.0.0"
HOLDOUT_IDS = {5, 10, 14, 18, 22, 26, 30}


def _sigmoid(value):
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def fit(rows, epochs=2200, learning_rate=0.08, l2=0.025):
    rows = rows + [dict(row, features=mirror_features(row["features"])) for row in rows]
    width = len(rows[0]["features"])
    means = [sum(row["features"][i] for row in rows) / len(rows)
             for i in range(width)]
    scales = []
    for i, mean in enumerate(means):
        variance = sum((row["features"][i] - mean) ** 2 for row in rows) / len(rows)
        scales.append(max(math.sqrt(variance), 1e-5))
    normalized = [[(value - means[i]) / scales[i]
                   for i, value in enumerate(row["features"])] for row in rows]

    positives = sum(row["target"] for row in rows)
    negatives = len(rows) - positives
    class_weight = {1: len(rows) / (2.0 * positives),
                    0: len(rows) / (2.0 * negatives)}
    weights = [0.0] * width
    bias = 0.0
    normalizer = sum(class_weight[row["target"]] for row in rows)

    for epoch in range(epochs):
        gradient = [0.0] * width
        bias_gradient = 0.0
        for row, values in zip(rows, normalized):
            prediction = _sigmoid(bias + sum(w * x for w, x in zip(weights, values)))
            error = (prediction - row["target"]) * class_weight[row["target"]]
            bias_gradient += error
            for i, value in enumerate(values):
                gradient[i] += error * value
        rate = learning_rate / (1.0 + epoch / 1800.0)
        for i in range(width):
            weights[i] -= rate * (gradient[i] / normalizer + l2 * weights[i])
        bias -= rate * bias_gradient / normalizer
    return means, scales, weights, bias


def make_model(rows, epochs=2200):
    means, scales, weights, bias = fit(rows, epochs=epochs)
    return {
        "model_version": MODEL_VERSION,
        "model_type": "regularized_logistic_regression",
        "feature_version": FEATURE_VERSION,
        "threshold": 0.5,
        "positive_label": "valid",
        "means": means,
        "scales": scales,
        "weights": weights,
        "bias": bias,
    }


def evaluate(model, rows):
    predictions = []
    for row in rows:
        score = probability(model, row["features"])
        predicted = int(score >= model["threshold"])
        predictions.append({"shot_id": row["shot_id"], "label": row["label"],
                            "valid_probability": round(score, 4),
                            "predicted": "valid" if predicted else "invalid",
                            "correct": predicted == row["target"]})
    accuracy = sum(item["correct"] for item in predictions) / len(predictions)
    valid_rows = [item for item in predictions if item["label"] == "valid"]
    invalid_rows = [item for item in predictions if item["label"] == "invalid"]
    valid_recall = sum(item["correct"] for item in valid_rows) / len(valid_rows)
    invalid_recall = sum(item["correct"] for item in invalid_rows) / len(invalid_rows)
    return {"accuracy": round(accuracy, 4),
            "balanced_accuracy": round((valid_recall + invalid_recall) / 2.0, 4),
            "valid_recall": round(valid_recall, 4),
            "invalid_recall": round(invalid_recall, 4),
            "predictions": predictions}


def fingerprint(labels_path, rows):
    digest = hashlib.sha256()
    for path in [labels_path] + [row["path"] for row in rows]:
        with open(path, "rb") as source:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="datasets/image_quality/data")
    parser.add_argument("--output", default="image_quality/model/quality_model.json")
    args = parser.parse_args()
    labels_path = os.path.join(args.dataset, "labels.csv")
    rows = []
    with open(labels_path, newline="") as source:
        for item in csv.DictReader(source):
            path = os.path.join(args.dataset, item["filename"])
            rows.append({"shot_id": int(item["shot_id"]), "label": item["label"],
                         "target": int(item["label"] == "valid"), "path": path,
                         "features": extract_features(path)})
    if len(rows) != 30 or len(rows[0]["features"]) != FEATURE_COUNT:
        raise SystemExit("expected 30 complete captures with the current feature schema")

    training_rows = [row for row in rows if row["shot_id"] not in HOLDOUT_IDS]
    holdout_rows = [row for row in rows if row["shot_id"] in HOLDOUT_IDS]
    holdout_model = make_model(training_rows)
    holdout = evaluate(holdout_model, holdout_rows)

    model = make_model(rows, epochs=2800)
    model["means"] = [round(value, 10) for value in model["means"]]
    model["scales"] = [round(value, 10) for value in model["scales"]]
    model["weights"] = [round(value, 10) for value in model["weights"]]
    model["bias"] = round(model["bias"], 10)
    model["training"] = {
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset_sha256": fingerprint(labels_path, rows),
        "samples": len(rows),
        "valid_samples": sum(row["target"] for row in rows),
        "invalid_samples": sum(not row["target"] for row in rows),
        "holdout_shot_ids": sorted(HOLDOUT_IDS),
        "holdout": holdout,
        "limitations": "Device-specific prototype; not clinically validated.",
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    temp = args.output + ".tmp"
    with open(temp, "w") as target:
        json.dump(model, target, indent=2)
    os.replace(temp, args.output)
    print(json.dumps({"ok": True, "output": args.output,
                      "holdout": holdout}, indent=2))


if __name__ == "__main__":
    main()
