# Training run record

The `praxis-freesolo-2.0` lineage was trained on 2026-07-19 with FreeSOLO
Flash `1.0.2`. The published environment is
`bananagoo/praxis-freesolo`. Training uses 194 deterministic examples and the
promotion suite uses 72 category-held-out examples.

## Results

| Stage | Run ID | Status | Train signal | Held-out full pass | Decision |
|---|---|---|---|---|---|
| SFT | `flash-1784438906-35d1b389` | done, deployed | loss `0.3728` to `0.0085`; final train loss `0.06965`; token accuracy `0.9959` | 72/72 (100%) | promoted |
| GRPO from SFT | `flash-1784440274-9798478f` | done, deployed | sampled reward `0.9375` to `1.0`, with non-flat intermediate batches | 70/72 (97.2%) | selected as active layered model |

SFT used 66 optimizer steps and cost `$0.22413662085470082`. Its immutable
deployed revision is
`flash-1784438906-35d1b389@final.83621eae0a066a5f28c271589175ac98d2e7e026`.

GRPO warm-started from that SFT adapter, ran 25 steps with 32 completions per
step, and cost `$0.11126034459367792`. Its immutable deployed revision is
`flash-1784440274-9798478f@final.d47f1a276df04a1861a2b4917a46598143fa5ba1`.

## Promotion decision

The SFT adapter passed every held-out category and every semantic check:
pattern, direction, grounding, non-diagnostic language, and permitted next
step. The GRPO adapter preserved 100% grounding, safety, and next-step rates,
but produced one real semantic failure on a capture-warning case: it returned
`mixed` instead of the required reliability override `unreliable`. A second
failure was a hosted HTTP 500 and is recorded separately as an inference
availability failure.

GRPO did not equal the SFT held-out gate. The project nevertheless explicitly
selects `flash-1784440274-9798478f` as the active model to use the complete
SFT-to-GRPO lineage. Backend semantic validation remains mandatory and rejects
an unreliable-case response if the model returns a directional pattern. This
selection does not erase or reinterpret the evaluation difference. See
`reports/sft.json` and `reports/grpo.json` for complete outputs and per-check
results; compare them with:

```bash
python3 scripts/compare_reports.py reports/sft.json reports/grpo.json
```

Never place a FreeSOLO API key in this file or any committed `.env` file.
