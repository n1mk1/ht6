# RehabTrace (FreeSolo / Flash)

Therapist-facing, non-diagnostic explanations of **deterministic** reference-vs-current
path-tracing session comparisons. FreeSolo does **not** process raw camera/IMU signals;
it converts an already-calculated comparison into grounded JSON for review.

## Flow

```text
Synthetic reference + current metrics
        → deterministic comparison (changes / reliability)
        → FreeSolo SFT model
        → grounded therapist-facing JSON
        → deterministic validation
```

## Quick start

```bash
# Regenerate synthetic train + held-out sets (deterministic seed=42)
python3 scripts/generate_dataset.py

# Validate every gold output against CONTRACT.md
python3 scripts/validate_dataset.py
# equivalent: python3 scripts/evaluate.py --validate-dataset

# Local demo: prompt construction + gold response validation
python3 scripts/demo.py

# Score an arbitrary response
python3 scripts/evaluate.py examples/demo_case.json examples/demo_case_gold_response.txt
```

## Flash / FreeSolo

```bash
flash --version
flash models

# Publish environment after editing environment.py or dataset/
flash env push --name rehabtrace-freesolo .

# Paste the returned id into configs/sft.toml [environment] id, then:
flash train configs/sft.toml --dry-run
flash train configs/sft.toml --cost

# Paid training (ask before running):
flash train configs/sft.toml
```

SFT settings: `Qwen/Qwen3.5-2B`, `thinking = false`, small curated dataset.

## Contract

See `CONTRACT.md` for the frozen input/output schema and grounding rules.

## Layout

| Path | Role |
|------|------|
| `CONTRACT.md` | Frozen I/O contract |
| `environment.py` | FreeSolo single-turn env + reward |
| `system_prompt.txt` | System prompt used by env + demo |
| `dataset/train.jsonl` | SFT rows `{"input","output"}` |
| `examples/test.jsonl` | Held-out evaluation cases |
| `examples/demo_case.json` | Fixed demo input |
| `configs/sft.toml` | Flash SFT config |
| `scripts/generate_dataset.py` | Deterministic dataset builder |
| `scripts/evaluate.py` | Response + dataset validator |
| `scripts/demo.py` | Local demo path |
| `scripts/regression.py` | Deployed-adapter regression (needs run id) |
