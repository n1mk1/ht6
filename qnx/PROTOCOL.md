# Praxis — establishing the accuracy & stability scale

Praxis reports two raw 0–100 scores plus a **Good / Fair / Poor** classification.
The raw scores are deterministic; the *class boundaries* are where judgement
enters. Inventing thresholds is not defensible, so this protocol anchors them to
**measured reference performance** instead.

> These are **prototype task-performance measures, not validated clinical
> metrics**. They do not diagnose, screen, or grade any condition. For an
> individual, the meaningful signal is **change across their own sessions**;
> the absolute Good/Fair/Poor bands are a coarse, task-specific descriptor.

## What is actually classified

Classification runs on the **physical measures**, not the 0–100 score, because
the physical quantities are interpretable and setup-independent:

| Class of | Measure | Units | Direction |
|---|---|---|---|
| Accuracy | `mean_dev_mm` (mean perpendicular deviation, red↔blue) | mm | lower = better |
| Stability | `tremor_rms_deg_s` (gyro jitter after removing intended motion) | °/s | lower = better |

Bands: `good` ≤ *GOOD*, `poor` > *POOR*, else `fair`. Defaults (provisional):
`ACC_GOOD_MM=4`, `ACC_POOR_MM=8`, `STAB_GOOD_DPS=3`, `STAB_POOR_DPS=7`.
Set them as environment variables when launching the server.

## Why you must calibrate per task template

`mean_dev_mm` depends on the pattern (a gentle curve is easier than a sharp
zig-zag) and the instructed speed; `tremor_rms` depends on tool weight and
grip. **Bands are only valid for one fixed template + setup + instruction set.**
Re-calibrate if any of those change, and record the template version with the
thresholds.

## Calibration protocol

### 1. Freeze the setup
Same printed pattern (record its `task.version`), same camera height and mat
position, same purple scale bar length, same verbal instructions and target
pace. Note them in the results file.

### 2. Collect anchor conditions
You are deliberately producing *known-good* and *known-poor* performances to
bracket the scale. Recruit several people (≥5 is better; even 2–3 helps) and
have each do these conditions, a few trials each:

**Accuracy anchors**
- **Careful** — "trace as accurately as you can, take your time." → *good* anchor
- **Natural** — "trace at a comfortable, normal pace." → *mid*
- **Degraded** — non-dominant hand (or fast/careless). → *poor* anchor

**Stability anchors**
- **Braced** — forearm supported, move slowly. → *good* anchor
- **Natural** — unsupported, normal pace. → *mid*
- **Perturbed** — deliberately shaky / unsupported / right after exertion. → *poor* anchor

Every run stores `mean_dev_mm` and `tremor_rms_deg_s` in
`sessions/<id>/session.json` — collect them per condition.

### 3. Set thresholds from the distributions
For each measure you now have three clusters (good / mid / poor). Set:
- **GOOD boundary** = ~75th percentile of the *careful / braced* cluster
  (most careful attempts land at "good").
- **POOR boundary** = ~25th percentile of the *degraded / perturbed* cluster
  (most degraded attempts land at "poor").
- Everything between is **fair**.

A quick, defensible first pass with limited data: take the **median of the good
condition** and the **median of the poor condition**; put GOOD at the good-median
and POOR at the poor-median.

### 4. Sanity-check and lock
Re-run a handful of fresh traces; confirm the labels match a human's eyeball
judgement of "clean / ok / messy." Nudge boundaries if needed. Record the final
thresholds **with**: template version, number of participants/trials, and date.

### 5. Individual tracking overrides the absolute bands
For a returning participant, compare **their** `mean_dev_mm` / `tremor_rms`
across sessions (within-person deltas). This removes between-person variation
and is far more reliable than the absolute Good/Fair/Poor label. Use the bands
for a first-glance summary; use the trend for actual progress.

## Applying calibrated thresholds

```bash
ACC_GOOD_MM=3 ACC_POOR_MM=7 STAB_GOOD_DPS=2.5 STAB_POOR_DPS=6 \
  ~/venv/bin/python server/server.py
```

The chosen bands are echoed into every `session.json` under
`scores.bands`, so each result records the scale it was judged against.
