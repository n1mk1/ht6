"""Guided-decoding response schema for Praxis FreeSOLO v2."""

from praxis_contract import ALLOWED_PATTERNS, METRIC_KEYS

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "overall_pattern": {"type": "string", "enum": sorted(ALLOWED_PATTERNS)},
        "observations": {
            "type": "array",
            "minItems": 2,
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "statement": {"type": "string", "minLength": 16, "maxLength": 320},
                    "metric_keys": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {"type": "string", "enum": list(METRIC_KEYS)},
                    },
                },
                "required": ["statement", "metric_keys"],
            },
        },
        "conflicts_or_limitations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {"type": "string", "minLength": 16, "maxLength": 320},
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
