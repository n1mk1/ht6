"""Deterministic evaluator for Praxis FreeSOLO responses.

Usage: python3 scripts/evaluate.py <input.json> <response.txt>
       python3 scripts/evaluate.py --validate-dataset
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contract_checks import check_response_text, check_structure, print_results  # noqa: E402


def validate_dataset():
    total = 0
    failures = 0
    train_inputs = set()

    with open(ROOT / "dataset" / "train.jsonl") as f:
        for i, line in enumerate(f):
            row = json.loads(line)
            input_data = json.loads(row["input"])
            output_data = json.loads(row["output"])
            train_inputs.add(row["input"])
            results = check_structure(input_data, output_data, output_data)
            total += 1
            if not all(ok for _, ok, _ in results):
                failures += 1
                print_results(f"dataset/train.jsonl:{i}", results)

    with open(ROOT / "examples" / "test.jsonl") as f:
        for i, line in enumerate(f):
            row = json.loads(line)
            input_data = row["input"]
            output_data = row["output"]
            results = check_structure(input_data, output_data, output_data)
            total += 1
            if not all(ok for _, ok, _ in results):
                failures += 1
                print_results(f"examples/test.jsonl:{i}", results)
            if json.dumps(input_data, sort_keys=True) in {
                json.dumps(json.loads(s), sort_keys=True) for s in train_inputs
            }:
                failures += 1
                print(f"--- examples/test.jsonl:{i} ---")
                print(
                    "  [FAIL] held_out_input_not_in_train -- input also present in training set"
                )

    print(f"\nvalidated {total} examples, {failures} failed")
    sys.exit(1 if failures else 0)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--validate-dataset":
        validate_dataset()
        return
    if len(sys.argv) != 3:
        print("Usage: python3 scripts/evaluate.py <input.json> <response.txt>")
        print("       python3 scripts/evaluate.py --validate-dataset")
        sys.exit(2)
    input_path, response_path = sys.argv[1], sys.argv[2]
    input_data = json.loads(Path(input_path).read_text())
    response_text = Path(response_path).read_text()
    results = check_response_text(input_data, response_text)
    ok = print_results(response_path, results)
    print("\nOVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
