"""Shared RehabTrace response JSON schema for training + regression guided decoding."""

METRIC_KEYS = [
    "path_inside_percent",
    "mean_deviation_mm",
    "max_deviation_mm",
    "completion_time_seconds",
    "pause_count",
    "correction_count",
    "angular_instability_rms",
    "peak_angular_velocity_dps",
]

CONFLICTS_ENUM = [
    "These results describe measured performance on this standardized task only.",
    "The task was completed more quickly, but path accuracy and deviation were worse.",
    "Accuracy improved, but the task was completed more slowly.",
    "Tracing accuracy improved, but movement stability during the task was worse.",
    "The current session's calibration did not pass validation, so this comparison is not considered reliable.",
    "This reflects a change in standardized task performance only and does not indicate a clinical outcome or confirm that therapy caused the change.",
    "These results describe measured performance on this standardized task only and do not explain why the values changed.",
    "Reference and current sessions use different task identifiers and must not be compared.",
    "Tracing accuracy was stable, but movement stability during the task was notably worse.",
    "IMU data capture for the current session was well below a usable threshold, so movement-quality measurements are not considered reliable.",
]

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "overall_pattern": {
            "type": "string",
            "enum": ["improved", "declined", "stable", "mixed", "unreliable"],
        },
        "observations": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "statement": {"type": "string"},
                    "metric_keys": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {"type": "string", "enum": METRIC_KEYS},
                    },
                },
                "required": ["statement", "metric_keys"],
            },
        },
        "conflicts_or_limitations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {"type": "string", "enum": CONFLICTS_ENUM},
        },
        "possible_next_step": {"type": "string"},
        "therapist_review_required": {"type": "boolean", "enum": [True]},
    },
    "required": [
        "overall_pattern",
        "observations",
        "conflicts_or_limitations",
        "possible_next_step",
        "therapist_review_required",
    ],
}
