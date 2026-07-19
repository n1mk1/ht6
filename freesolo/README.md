# Praxis FreeSOLO

This directory contains the isolated post-training and inference contract for
turning a deterministic comparison of two compatible Praxis path-tracing runs
into concise, therapist-facing JSON. FreeSOLO does not process sensor streams,
calculate scores, choose a baseline, or make clinical conclusions.

## What the model does

The model receives versioned QNX scores, physical measurements, quality fields,
and changes already calculated by deterministic code. It returns:

- an `improved`, `declined`, `stable`, `mixed`, or `unreliable` task pattern;
- exactly two grounded observations covering accuracy and stability;
- limitations and one contract-approved review step; and
- `therapist_review_required: true`.

It is a structured explanation model, not a diagnostic or outcome-prediction
model. The backend rejects malformed, ungrounded, semantically incorrect, or
clinically unsafe responses before persistence.

## Data

`data/qnx_calibration_anchors.json` contains deidentified physical ranges from
two QNX calibration bundles. Usernames, device IDs, timestamps, traces, and raw
sensor data are not committed. These two runs are prototype anchors, not
clinical norms and not a longitudinal pair.

`scripts/generate_dataset.py` deterministically produces:

- 194 SFT/GRPO training examples across improvement, decline, stable, mixed,
  contextual-speed, low-coverage, and quality-failure cases; and
- 72 held-out examples, including fully held-out vision, capture-warning,
  task-mismatch, and score-version-mismatch categories.

The synthetic examples use the fetched physical ranges and the current
`praxis-score-1.1.0` scale. The original `1.0.0` anchor scores are retained only
as provenance because scores from different versions are not directly
comparable.

## Local verification

```bash
python3 scripts/generate_dataset.py
python3 scripts/validate_dataset.py
python3 -m unittest discover -s tests -v
python3 scripts/demo.py
```

The reward is semantic, not format-only. Fabricated numbers and unsafe clinical
claims score zero. Correct structure, grounding, task pattern, observation
directions, reliability handling, and next-step selection receive separate
reward components.

## SFT then GRPO

Install and authenticate the repository-local CLI:

```bash
python3 -m venv .venv
.venv/bin/pip install freesolo-flash
.venv/bin/flash login --api-key fslo_...
.venv/bin/flash whoami
```

Publish the exact environment and verify that the returned ID matches the
`[environment].id` value in both configs:

```bash
.venv/bin/flash env push --name praxis-freesolo .
.venv/bin/flash train configs/sft.toml --dry-run
.venv/bin/flash train configs/sft.toml --cost
.venv/bin/flash train configs/sft.toml
```

Wait for SFT to reach `done`. Replace `REPLACE_WITH_SFT_RUN_ID` in
`configs/rl.toml` with that run ID, then warm-start GRPO:

```bash
.venv/bin/flash train configs/rl.toml --dry-run
.venv/bin/flash train configs/rl.toml --cost
.venv/bin/flash train configs/rl.toml
```

Deploy each candidate and evaluate all held-out cases:

```bash
.venv/bin/flash deploy <sft-run-id> --dry-run
.venv/bin/flash deploy <sft-run-id>
.venv/bin/flash deployments --json
export FREESOLO_ENDPOINT=<openai_base_url-from-deployments>/chat/completions
python3 scripts/regression.py <sft-run-id> --output reports/sft.json

.venv/bin/flash deploy <grpo-run-id> --dry-run
.venv/bin/flash deploy <grpo-run-id>
python3 scripts/regression.py <grpo-run-id> --output reports/grpo.json
python3 scripts/compare_reports.py reports/sft.json reports/grpo.json
```

Do not promote GRPO merely because training reward rose. It must preserve
grounding and safety and improve held-out semantic pass rates outside the noise
expected from 72 examples. Record evidence in `TRAINING_RUNS.md`.

Praxis currently selects the layered GRPO run `flash-1784440274-9798478f` so
the deployed integration demonstrates the complete SFT-to-GRPO lineage. Its
70/72 held-out result and capture-warning limitation remain documented and are
still enforced by backend semantic validation. See `LAYERED_MODEL.md`.

These commands follow the official [FreeSOLO training](https://freesolo.co/docs/guides/training)
and [deployment](https://freesolo.co/docs/guides/deploy-and-chat)
guides. `structured_outputs` is intentionally present only in the GRPO config,
as required by the platform.

## Layout

| Path | Role |
|---|---|
| `CONTRACT.md` | Versioned input/output and safety contract |
| `praxis_contract.py` | Deterministic semantics, evaluator, and dense reward |
| `environment.py` | FreeSOLO single-turn environment entry point |
| `system_prompt.txt` | Inference and training system prompt |
| `dataset/train.jsonl` | Generated training rows |
| `examples/test.jsonl` | Generated held-out rows |
| `configs/sft.toml` | Reproducible SFT configuration |
| `configs/rl.toml` | SFT-warm-started GRPO configuration |
| `scripts/regression.py` | Deployed-adapter held-out evaluator |
| `TRAINING_RUNS.md` | Run IDs, metrics, and promotion decision |
| `LAYERED_MODEL.md` | Active SFT-to-GRPO lineage and integration record |
