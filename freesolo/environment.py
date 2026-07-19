"""RehabTrace Freesolo environment.

Single-turn task: convert a deterministic reference-vs-current session
comparison (path-tracing task) into a concise, grounded, non-diagnostic
therapist-facing explanation. See dataset/train.jsonl for training rows,
CONTRACT.md for the frozen input/output schema, and TRAINING.md for how
Flash trains this.
"""

from __future__ import annotations

import json
from pathlib import Path

from freesolo.datasets.types import TaskExample
from freesolo.environments import EnvironmentSingleTurn, RewardResult


DEFAULT_DATASET_PATH = Path(__file__).parent / "dataset" / "train.jsonl"

SYSTEM_PROMPT = """You explain a deterministic comparison between a rehabilitation participant's reference session and current session on the same standardized path-tracing task, for therapist review.

Rules:
- Only use facts and numbers present in the input's reference_session, current_session, and changes. Never invent measurements or recompute differences yourself -- all changes are already calculated.
- Every metric_keys entry you cite must be one of the 8 metric keys present in "changes".
- possible_next_step must be copied verbatim from the input's permitted_next_steps list -- never invent a next step.
- therapist_review_required must always be true.
- If comparison_reliability is "unreliable", overall_pattern must be "unreliable", and you must not claim improvement or decline -- name the specific data-quality problem in conflicts_or_limitations instead.
- Never diagnose a condition, claim neurological recovery, claim therapy is working, or recommend treatment independently. This is a task-performance measurement, not a clinical or diagnostic outcome. Never use words like "recovered," "remission," "relapse," "disease," or "stroke."
- Respond with ONLY valid JSON, no Markdown fences, no extra text, matching exactly this schema:
{"overall_pattern": "improved"|"declined"|"stable"|"mixed"|"unreliable", "observations": [{"statement": string, "metric_keys": [string]}] (exactly 2 entries), "conflicts_or_limitations": [string], "possible_next_step": string, "therapist_review_required": true}"""

REQUIRED_KEYS = {"overall_pattern", "observations", "conflicts_or_limitations",
                 "possible_next_step", "therapist_review_required"}


def load_jsonl(path: str | Path):
    rows = []
    with Path(path).open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def validity_reward(example: TaskExample, response_text: str) -> RewardResult:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return RewardResult(score=0.0, threshold=1.0)
    if not isinstance(data, dict) or not REQUIRED_KEYS.issubset(data.keys()):
        return RewardResult(score=0.0, threshold=1.0)
    return RewardResult(score=1.0, threshold=1.0)


class RehabTraceEnv(EnvironmentSingleTurn):
    dataset = load_jsonl(DEFAULT_DATASET_PATH)

    def build_prompt_messages(self, example: TaskExample, prompt_text: str):
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": example.input},
        ]

    def score_response(self, example: TaskExample, response_text: str) -> RewardResult:
        return validity_reward(example, response_text)


def load_environment(dataset_path: str | None = None, **kwargs) -> RehabTraceEnv:
    env = RehabTraceEnv()
    if dataset_path:
        env.dataset = load_jsonl(dataset_path)
    return env
