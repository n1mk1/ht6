# Training run record

No paid `praxis-freesolo-2.0` training run has been created from this branch
yet. The local CLI is FreeSOLO Flash `1.0.2`, authenticated to the project
account, and the environment is published as `bananagoo/praxis-freesolo`.

Authenticated SFT dry-run `flash-1784438740-9f31df69` passed with exact
client/server schema agreement. After billing was enabled, SFT run
`flash-1784438906-35d1b389` completed and published its final adapter.

Local config estimates on 2026-07-19 parsed successfully:

- SFT: 98 steps, approximately 9.7 billable training minutes, estimated `$0.22`.
- GRPO: 25 steps with 32 rollouts per step, approximately 4.8 billable training
  minutes, estimated `$0.11`; the final quote depends on resolving the SFT
  adapter rank during authenticated dry-run.

## Required evidence

| Stage | Run ID | Status | Train signal | Held-out full pass | Decision |
|---|---|---|---|---|---|
| SFT | `flash-1784438906-35d1b389` | done | loss `0.3728` to `0.0085`; final token accuracy `0.9959` | pending | awaiting held-out evaluation |
| GRPO from SFT | pending | not submitted | pending | pending | not evaluated |

For each run, add:

- the immutable run ID and environment ID;
- final SFT loss or GRPO reward trend from `flash log`;
- GRPO `full_contract_pass` and `grounded_safe` reward metrics, kept separate
  from the shaped optimization score;
- the 72-case JSON report from `scripts/regression.py`;
- rates for pattern correctness, direction correctness, grounding, safety, and
  next-step correctness;
- representative failure outputs; and
- the reason the candidate was promoted or rejected.

The backend should point `PRAXIS_FREESOLO_MODEL` only at the selected deployed
run. Never place a FreeSOLO API key in this file or any committed `.env` file.
