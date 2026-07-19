# Praxis FreeSOLO contract

Contract version: `praxis-freesolo-2.0`

## Boundary

The backend selects two runs and calculates their changes. FreeSOLO only
describes those supplied values. It must not process raw camera/IMU data,
recalculate a metric, select another baseline, infer a cause, recommend
treatment, diagnose a condition, or compare against population norms.

The sessions are directly interpretable only when task type, task version,
difficulty, hand metadata, and score version are compatible and required
capture-quality checks pass. Otherwise `comparison_reliability` is
`unreliable`, which overrides any apparent direction.

## Input

```json
{
  "contract_version": "praxis-freesolo-2.0",
  "participant_id": "string",
  "reference_session": {
    "session_id": "string",
    "timestamp": "RFC 3339 string",
    "task": {"type": "string", "version": "string", "difficulty": 1, "hand": "right"},
    "score_version": "string",
    "scores": {"accuracy": 90.0, "stability": 90.0},
    "metrics": {
      "coverage_pct": 72.4,
      "mean_dev_mm": 1.86,
      "max_dev_mm": 5.0,
      "rms_dev_mm": 2.22,
      "completion_time_seconds": 42.3,
      "tremor_rms_deg_s": 5.18,
      "peak_angular_velocity_deg_s": 31.5
    },
    "quality": {
      "calibration_valid": true,
      "n_ref_slices": 140,
      "n_scored_slices": 101,
      "imu_samples_received": 6380,
      "imu_samples_invalid": 2,
      "imu_rate_hz": 151.0,
      "warnings": []
    }
  },
  "current_session": "same shape as reference_session",
  "changes": {
    "accuracy_score": {
      "reference": 90.0,
      "current": 82.0,
      "absolute_change": -8.0,
      "direction": "declined",
      "contextual": false
    }
  },
  "comparison_reliability": "reliable",
  "reliability_reasons": [],
  "permitted_next_steps": ["contract-controlled strings"]
}
```

`changes` contains all nine keys: `accuracy_score`, `stability_score`,
`coverage_pct`, `mean_dev_mm`, `max_dev_mm`, `rms_dev_mm`,
`completion_time_seconds`, `tremor_rms_deg_s`, and
`peak_angular_velocity_deg_s`.

## Output

```json
{
  "overall_pattern": "declined",
  "observations": [
    {"statement": "string", "metric_keys": ["accuracy_score"]},
    {"statement": "string", "metric_keys": ["stability_score"]}
  ],
  "conflicts_or_limitations": ["string"],
  "possible_next_step": "exact contract-controlled string",
  "therapist_review_required": true
}
```

The object has exactly these five keys. There are exactly two observations and
one or two limitations. Both primary dimensions must be cited.

## Deterministic semantics

- Accuracy/stability both stable: `stable`.
- At least one improves and neither declines: `improved`.
- At least one declines and neither improves: `declined`.
- One improves and one declines: `mixed`.
- Any recorded reliability reason: `unreliable`.
- Completion time and peak angular velocity are contextual and never determine
  the overall pattern.

Every number in an observation must exactly match a supplied input value. Each
observation must describe the direction of its cited non-contextual metrics.
For unreliable inputs, observations may state recorded values but must not
claim improvement or decline, and a supplied reliability reason must be
explained.

The output describes performance on the measured task only. It is not a
diagnosis, validated clinical deterioration, evidence of recovery, or a
treatment recommendation.
