"""FreeSOLO single-turn environment for Praxis SFT and warm-start GRPO."""

from __future__ import annotations

import json
from pathlib import Path

from freesolo.datasets.types import TaskExample
from freesolo.environments import EnvironmentSingleTurn, RewardMetric, RewardResult

from praxis_contract import CONTRACT_VERSION, reward_response

ROOT = Path(__file__).parent
DEFAULT_DATASET_PATH = ROOT / "dataset" / "train.jsonl"
SYSTEM_PROMPT = (ROOT / "system_prompt.txt").read_text().strip()


def load_jsonl(path: str | Path) -> list[dict]:
    with Path(path).open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _json_value(value: object) -> dict:
    if isinstance(value, dict):
        return value
    return json.loads(str(value))


class PraxisComparisonEnv(EnvironmentSingleTurn):
    dataset = load_jsonl(DEFAULT_DATASET_PATH)

    def build_prompt_messages(self, example: TaskExample, prompt_text: str):
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": str(example.input)},
        ]

    def score_response(self, example: TaskExample, response_text: str) -> RewardResult:
        try:
            input_data = _json_value(example.input)
            expected_output = _json_value(example.output)
            score, results = reward_response(
                input_data, expected_output, str(response_text)
            )
            checks = {name: ok for name, ok, _ in results}
            failed = [name for name, ok, _ in results if not ok]
            return RewardResult(
                score=score,
                threshold=1.0,
                metrics=(
                    RewardMetric(name="full_contract_pass", score=float(score == 1.0)),
                    RewardMetric(
                        name="grounded_safe",
                        score=float(
                            checks.get("numbers_grounded", False)
                            and checks.get("safe_non_diagnostic_language", False)
                        ),
                    ),
                ),
                error=", ".join(failed) if score == 0.0 and failed else None,
            )
        except (TypeError, ValueError, json.JSONDecodeError, KeyError) as error:
            return RewardResult(
                score=0.0,
                threshold=1.0,
                metrics=(
                    RewardMetric(name="full_contract_pass", score=0.0),
                    RewardMetric(name="grounded_safe", score=0.0),
                ),
                error=str(error),
            )


def load_environment(dataset_path: str | None = None, **kwargs) -> PraxisComparisonEnv:
    environment = PraxisComparisonEnv()
    if dataset_path:
        environment.dataset = load_jsonl(dataset_path)
    return environment


__all__ = ["CONTRACT_VERSION", "PraxisComparisonEnv", "load_environment"]
