# Praxis score calibration protocol

Praxis maps two physical task measurements onto versioned 0–100 scores:

| Score | Source measurement | Direction |
|---|---|---|
| Accuracy | `mean_dev_mm`, perpendicular red-to-blue path deviation | Lower is better |
| Stability | `tremor_rms_deg_s`, high-frequency gyro residual | Lower is better |

The current scale uses measured good and deliberately degraded anchor sessions.
It then assigns one of five score bands: `very low`, `low`, `moderate`, `high`,
or `very high`. These bands describe prototype task performance; they are not
clinical thresholds.

> Calibration cannot validate the metric clinically. Praxis should be used for
> within-person, compatible-session comparison unless a separate validation
> study supports a broader interpretation.

## Freeze the task and setup

Before collecting calibration runs, hold all relevant conditions constant:

- printed pattern and `task.version`;
- task difficulty and instructed pace;
- camera height, paper placement, focus, and lighting;
- `SCALE_PX_PER_MM` rig calibration;
- pen, IMU mounting, grip instructions, and hand metadata; and
- score implementation and `SCORE_VERSION`.

Create a new task version or calibration set when one of these materially
changes. Do not compare incompatible versions.

## Collect anchor conditions

Use several participants and multiple trials per condition when possible. Keep
the original run bundles and record the intended condition separately from the
measured result.

Accuracy conditions:

- **Careful:** trace as accurately as possible at a comfortable pace.
- **Natural:** trace normally using the standard instruction.
- **Degraded:** deliberately trace inaccurately, use the non-dominant hand, or
  use another predefined reproducible perturbation.

Stability conditions:

- **Braced:** forearm supported with slow deliberate motion.
- **Natural:** standard unsupported task performance.
- **Perturbed:** a predefined deliberately unstable condition.

Do not treat the intended label as proof that a run is usable. Exclude runs with
capture, calibration, or missing-data quality warnings before deriving anchors.

## Derive score anchors

The mapping in `praxis/score.py` uses a good physical anchor at score 90 and a
bad physical anchor at score 10. Values beyond those anchors continue linearly
to 100 and 0 and are clamped.

For each physical measure:

1. Inspect distributions by participant and condition.
2. Select a robust good anchor from usable careful/braced runs.
3. Select a robust bad anchor from usable degraded/perturbed runs.
4. Verify that the anchors are ordered, separated, and reproducible on held-out
   runs.
5. Record the source sessions, participants, task version, setup, and date.

The current prototype anchors are:

| Constant | Value | Maps to |
|---|---:|---:|
| `ACC_GOOD_MM` | 1.86 mm | accuracy 90 |
| `ACC_BAD_MM` | 13.04 mm | accuracy 10 |
| `STAB_GOOD_DPS` | 5.18 deg/s | stability 90 |
| `STAB_BAD_DPS` | 35.91 deg/s | stability 10 |

These values are implementation anchors from the existing prototype sessions,
not population norms.

## Update and version the implementation

Anchors are constants in `qnx/praxis/score.py`; the server does not read the
obsolete `ACC_GOOD_MM`, `ACC_POOR_MM`, `STAB_GOOD_DPS`, or `STAB_POOR_DPS`
three-band environment settings described by earlier versions of this file.

For any anchor, formula, tolerance, or band-boundary change:

1. update `qnx/praxis/score.py`;
2. increment `SCORE_VERSION`;
3. add or update scoring tests;
4. document the calibration evidence; and
5. avoid comparing scores from different versions as if they share one scale.

Every `session.json` stores its score version and complete
`score_definitions`, preserving the interpretation used at capture time.

## Validate the revised scale

Run held-out careful, natural, and degraded trials and verify:

- repeated runs under the same condition have acceptable variability;
- careful/braced and degraded/perturbed distributions are meaningfully
  separated;
- quality failures produce warnings or null values rather than plausible
  fabricated scores; and
- within-person changes agree with the physical measurements, not just the
  displayed band.

Run the deterministic unit checks after any change:

```bash
python3 qnx/tests/test_praxis.py
```

Reference-set percentiles are a separate calibration problem. They require at
least 20 real compatible samples per task/version/difficulty stratum and must
carry their own reference-set version and population description.
