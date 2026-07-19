from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class FakeTaskExample:
    input: object
    output: object


@dataclass
class FakeRewardMetric:
    name: str
    score: float


@dataclass
class FakeRewardResult:
    score: float
    threshold: float
    metrics: tuple[FakeRewardMetric, ...] = ()
    error: str | None = None


class FakeEnvironmentSingleTurn:
    pass


def load_environment_module():
    freesolo = types.ModuleType("freesolo")
    datasets = types.ModuleType("freesolo.datasets")
    dataset_types = types.ModuleType("freesolo.datasets.types")
    environments = types.ModuleType("freesolo.environments")
    dataset_types.TaskExample = FakeTaskExample
    environments.EnvironmentSingleTurn = FakeEnvironmentSingleTurn
    environments.RewardMetric = FakeRewardMetric
    environments.RewardResult = FakeRewardResult
    modules = {
        "freesolo": freesolo,
        "freesolo.datasets": datasets,
        "freesolo.datasets.types": dataset_types,
        "freesolo.environments": environments,
    }
    spec = importlib.util.spec_from_file_location(
        "praxis_freesolo_environment", ROOT / "environment.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class EnvironmentTests(unittest.TestCase):
    def test_environment_wires_gold_reward_and_clean_metrics(self):
        module = load_environment_module()
        row = json.loads((ROOT / "dataset" / "train.jsonl").read_text().splitlines()[0])
        example = FakeTaskExample(input=row["input"], output=row["output"])

        result = module.PraxisComparisonEnv().score_response(example, row["output"])

        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.threshold, 1.0)
        self.assertEqual(
            {metric.name: metric.score for metric in result.metrics},
            {"full_contract_pass": 1.0, "grounded_safe": 1.0},
        )

    def test_environment_returns_zero_instead_of_raising_on_bad_output(self):
        module = load_environment_module()
        row = json.loads((ROOT / "dataset" / "train.jsonl").read_text().splitlines()[0])
        example = FakeTaskExample(input=row["input"], output=row["output"])

        result = module.PraxisComparisonEnv().score_response(example, "not json")

        self.assertEqual(result.score, 0.0)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.metrics[0].score, 0.0)


if __name__ == "__main__":
    unittest.main()
