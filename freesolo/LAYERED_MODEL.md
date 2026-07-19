# Praxis layered FreeSOLO model

Praxis uses a single layered FreeSOLO adapter for session-comparison
explanations. The active run is:

```text
flash-1784440274-9798478f
```

This is not an independent GRPO model. It continued training directly from the
completed SFT adapter, so the model lineage is:

```text
Qwen/Qwen3.5-4B
  -> SFT:  flash-1784438906-35d1b389
  -> GRPO: flash-1784440274-9798478f
```

## Layer 1: supervised fine-tuning

SFT taught the `praxis-freesolo-2.0` JSON contract, deterministic comparison
language, metric grounding, quality limitations, non-diagnostic wording, and
the permitted review steps. It trained on 194 deterministically generated
examples based on deidentified QNX calibration ranges.

- Run: `flash-1784438906-35d1b389`
- Optimizer steps: 66
- Loss samples: `0.3728` to `0.0085`
- Final train loss: `0.06965`
- Final token accuracy: `0.9959`
- Held-out contract result: 72/72

## Layer 2: GRPO reinforcement learning

GRPO warm-started from the SFT adapter through the following real Flash
configuration boundary:

```toml
[train]
init_from_adapter = "flash-1784438906-35d1b389"
```

It optimized a dense contract reward over structure, grounding, deterministic
pattern selection, metric direction, reliability handling, safe language, and
the permitted next step. Fabricated measurements or unsafe clinical claims
receive zero reward.

- Run: `flash-1784440274-9798478f`
- Steps: 25
- Completions per step: 32
- Sampled reward: `0.9375` to `1.0`
- Held-out contract result: 70/72 (97.2%)
- Grounding, non-diagnostic language, and next-step checks: 100%

The two held-out failures were one hosted inference HTTP 500 and one real
capture-warning error where the model returned `mixed` rather than the required
`unreliable` override. The result is recorded without presenting 97.2% as
clinical validation. Praxis uses this layered run by explicit project choice;
backend semantic validation rejects responses that violate the reliability
override or other contract rules.

## Backend integration

The web application does not import FreeSOLO training code. The backend calls
the deployed adapter through the OpenAI-compatible HTTP service boundary:

```dotenv
PRAXIS_FREESOLO_MODE=http
PRAXIS_FREESOLO_ENDPOINT=https://clado-ai--freesolo-lora-serving.modal.run/v1/chat/completions
PRAXIS_FREESOLO_MODEL=flash-1784440274-9798478f
PRAXIS_FREESOLO_API_KEY=<local-secret>
```

The API key belongs only in an ignored local `.env` or deployment secret store.
The backend builds deterministic changes first, sends only the narrow versioned
comparison payload, validates returned JSON and semantics, and stores the model
run ID with accepted analysis. FreeSOLO never selects baselines, calculates
Praxis scores, processes raw traces, or writes directly to MongoDB.

## User-facing meaning

The frontend labels this output as FreeSOLO session analysis and keeps it
separate from raw measurements and deterministic comparisons. The analysis is
for review, not a diagnosis, prognosis, or validated indication of clinical
deterioration. Model-pending, unavailable, and rejected-response states must
remain visible rather than being replaced with generated fallback results.

Full run evidence is in `TRAINING_RUNS.md`, `reports/sft.json`, and
`reports/grpo.json`.
