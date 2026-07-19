from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from praxis_contract import (  # noqa: E402
    CONTRACT_VERSION,
    METRIC_KEYS,
    check_structure,
    reward_response,
)


def held_out_row(category: str | None = None) -> dict:
    for line in (ROOT / "examples" / "test.jsonl").read_text().splitlines():
        row = json.loads(line)
        if category is None or row["category"] == category:
            return row
    raise AssertionError(f"held-out category not found: {category}")


class ContractTests(unittest.TestCase):
    def test_all_gold_examples_receive_full_reward(self):
        for path in (
            ROOT / "dataset" / "train.jsonl",
            ROOT / "examples" / "test.jsonl",
        ):
            for line in path.read_text().splitlines():
                row = json.loads(line)
                input_data = (
                    row["input"]
                    if isinstance(row["input"], dict)
                    else json.loads(row["input"])
                )
                output = (
                    row["output"]
                    if isinstance(row["output"], dict)
                    else json.loads(row["output"])
                )
                score, results = reward_response(input_data, output, json.dumps(output))
                self.assertEqual(
                    score, 1.0, [result for result in results if not result[1]]
                )

    def test_wrong_pattern_cannot_receive_full_reward(self):
        row = held_out_row("clear_decline")
        wrong = copy.deepcopy(row["output"])
        wrong["overall_pattern"] = "stable"
        score, results = reward_response(row["input"], row["output"], json.dumps(wrong))
        self.assertLess(score, 1.0)
        self.assertIn(
            ("overall_pattern_correct", False),
            [(name, ok) for name, ok, _ in results],
        )

    def test_fabricated_number_is_zero_reward(self):
        row = held_out_row("clear_improvement")
        wrong = copy.deepcopy(row["output"])
        wrong["observations"][0]["statement"] += " The unsupported value was 999."
        score, _ = reward_response(row["input"], row["output"], json.dumps(wrong))
        self.assertEqual(score, 0.0)

    def test_unsafe_clinical_claim_is_zero_reward(self):
        row = held_out_row("clear_improvement")
        wrong = copy.deepcopy(row["output"])
        wrong["conflicts_or_limitations"] = [
            "The participant recovered because therapy is working."
        ]
        score, _ = reward_response(row["input"], row["output"], json.dumps(wrong))
        self.assertEqual(score, 0.0)

    def test_fully_held_out_reliability_cases_are_enforced(self):
        for category in (
            "unreliable_missing_vision",
            "unreliable_capture_warning",
            "unreliable_score_version_mismatch",
            "unreliable_task_mismatch",
        ):
            row = held_out_row(category)
            self.assertEqual(row["input"]["comparison_reliability"], "unreliable")
            self.assertEqual(row["output"]["overall_pattern"], "unreliable")
            self.assertTrue(
                all(
                    ok
                    for _, ok, _ in check_structure(
                        row["input"], row["output"], row["output"]
                    )
                )
            )

    def test_contract_uses_only_actual_qnx_metrics(self):
        self.assertEqual(CONTRACT_VERSION, "praxis-freesolo-2.0")
        self.assertEqual(
            set(METRIC_KEYS),
            {
                "accuracy_score",
                "stability_score",
                "coverage_pct",
                "mean_dev_mm",
                "max_dev_mm",
                "rms_dev_mm",
                "completion_time_seconds",
                "tremor_rms_deg_s",
                "peak_angular_velocity_deg_s",
            },
        )

    def test_anchor_file_is_deidentified_and_physical_values_are_preserved(self):
        raw = (ROOT / "data" / "qnx_calibration_anchors.json").read_text()
        anchors = json.loads(raw)
        self.assertNotIn('"username":', raw.lower())
        self.assertNotIn('"trace":', raw.lower())
        self.assertEqual(anchors["good_anchor"]["metrics"]["mean_dev_mm"], 1.86)
        self.assertEqual(anchors["bad_anchor"]["metrics"]["mean_dev_mm"], 13.04)
        self.assertEqual(anchors["good_anchor"]["metrics"]["tremor_rms_deg_s"], 5.18)
        self.assertEqual(anchors["bad_anchor"]["metrics"]["tremor_rms_deg_s"], 35.91)


if __name__ == "__main__":
    unittest.main()
