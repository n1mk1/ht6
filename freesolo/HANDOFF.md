# FreeSOLO implementation handoff

The active model contract is `praxis-freesolo-2.0`. Start with `README.md`,
`CONTRACT.md`, and `TRAINING_RUNS.md`; the longer platform guidance remains in
`TRAINING.md`.

## Current state

- QNX-derived calibration anchors are committed only in deidentified form.
- The generated corpus has 194 training and 72 held-out examples.
- Dataset, semantic, safety, and grounding tests pass locally.
- SFT uses Qwen 3.5 4B with a rank-16 LoRA for two epochs.
- GRPO must warm-start from the completed SFT run.
- The backend maps only real QNX schema `3.0` fields and validates model output
  independently before storing it.
- The production adapter never fabricates a regression score or confidence.

## Next external action

Authenticate the local CLI, publish the environment, and execute the commands
in `README.md`. Record every run ID, status, config, held-out report, and
promotion decision in `TRAINING_RUNS.md`.

Do not call a run successful because it was submitted or because JSON was
valid. A candidate is acceptable only after the held-out evaluator confirms
correct pattern selection, directions, reliability handling, grounding, and
safe language.
