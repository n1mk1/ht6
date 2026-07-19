# RehabTrace FreeSolo Contract (frozen)

## Task
Single-turn: given a deterministic comparison between a participant's reference
and current session on the same standardized path-tracing task, produce a
concise, grounded, non-diagnostic therapist-facing explanation. The model
never computes numbers itself — all values in `changes` are pre-calculated
and authoritative.

## Input shape

{
"participant_id": string,
"task_type": "path_tracing",
"reference_session": {
"session_id": string, "timestamp": string,
"metrics": {
"path_inside_percent": number, "mean_deviation_mm": number,
"max_deviation_mm": number, "completion_time_seconds": number,
"pause_count": int, "correction_count": int,
"angular_instability_rms": number, "peak_angular_velocity_dps": number
},
"quality": {
"camera_tracking_percent": number, "imu_capture_percent": number,
"calibration_valid": bool, "dropped_frame_count": int,
"dropped_sample_count": int, "warnings": [string]
}
},
"current_session": { <same shape as reference_session> },
"changes": {
"<one of the 8 metric keys above>": {
"absolute_change": number,
"direction": "improved" | "declined" | "stable"
},
... one entry per metric key ...
},
"comparison_reliability": "reliable" | "unreliable",
"permitted_next_steps": [string, ...]   // varies per input; model must pick from THIS list
}



Assumption: `"stable"` is a valid `direction` value (needed for the "mostly stable" scenario category — your example only showed improved/declined).

## Output schema (must match exactly, no Markdown fences, no extra text)
{
"overall_pattern": "improved" | "declined" | "stable" | "mixed" | "unreliable",
"observations": [
{ "statement": string, "metric_keys": [string, ...] }
],                              // exactly 2 or 3 entries
"conflicts_or_limitations": [string, ...],   // may be empty list
"possible_next_step": string,   // must exactly equal one entry in input.permitted_next_steps
"therapist_review_required": true            // always literally true
}



## Grounding rules (hard constraints)
- Every `metric_keys` entry cited in `observations` must be one of the 8 metric keys that appear in `changes`.
- Every number mentioned in any `statement` must literally match a value from `reference_session.metrics`, `current_session.metrics`, or `changes` — never invented, never recomputed.
- `possible_next_step` must be copied verbatim from `input.permitted_next_steps` — never invented.
- `therapist_review_required` is always `true` — never conditional.
- If `comparison_reliability == "unreliable"`, `overall_pattern` must be `"unreliable"`, and no improvement/decline claim may appear anywhere in the output; `conflicts_or_limitations` must name the specific quality problem (e.g. low camera tracking, invalid calibration).
- Never use language implying diagnosis, recovery, disease, or independent treatment recommendations (per the safe-language list in the original spec).

## `overall_pattern` decision rule
- `improved` — the important metrics broadly moved in the improved direction
- `declined` — the important metrics broadly moved in the declined direction
- `stable` — changes are small/inconsistent with no meaningful overall direction
- `mixed` — some important dimensions improved, others declined
- `unreliable` — data quality makes the comparison unsafe to interpret (overrides all of the above)

## Product framing: relapse / plateau / return-to-baseline
These are product concepts, not new schema fields — they map onto the existing
`overall_pattern` values with no contract change:
- "Relapse" -> `declined` (current session declined relative to reference)
- "Plateau" -> `stable` (current session is stable relative to reference)
- "Return to / matches earlier baseline" -> `improved` or `stable`, when the
  backend sets `reference_session` to an earlier baseline rather than the
  immediately-prior session

Language rule: never use "remission," "relapse," or other disease-recurrence
or recovery terms in generated text. Use neutral task-performance phrasing:
- Instead of "relapsed" -> "performance declined relative to the reference session"
- Instead of "in remission" / "recovered" -> "current performance matches (or
  exceeds) the reference session"

FreeSolo never chooses which session is the reference — that is a backend/
therapist decision already reflected in the input's `reference_session`.
