from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import Settings

METRIC_ALIASES = {
    "path_inside_percent": ("path_inside_percent",),
    "mean_deviation_mm": ("mean_deviation_mm", "mean_dev_mm"),
    "max_deviation_mm": ("max_deviation_mm", "max_dev_mm"),
    "completion_time_seconds": ("completion_time_seconds",),
    "pause_count": ("pause_count",),
    "correction_count": ("correction_count",),
    "angular_instability_rms": ("angular_instability_rms",),
    "peak_angular_velocity_dps": (
        "peak_angular_velocity_dps",
        "peak_angular_velocity_deg_s",
    ),
}
ALLOWED_PATTERNS = {"improved", "declined", "stable", "mixed", "unreliable"}
METRIC_KEYS = list(METRIC_ALIASES)
PERMITTED_STEPS = [
    "Repeat the same standardized task at the next planned session.",
    "Review the accuracy-versus-speed tradeoff with the participant.",
    "Confirm that the same task setup and calibration are used next time.",
    "Collect another session before drawing a broader conclusion.",
]
SYSTEM_PROMPT = """You explain a deterministic comparison between a rehabilitation
participant's reference session and current session on the same standardized
path-tracing task, for therapist review. Use only input facts. Return only valid
JSON matching the supplied schema. Never diagnose, claim recovery, infer causes,
or recommend treatment. therapist_review_required must be true."""
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
            "items": {"type": "string"},
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


@dataclass
class AnalysisResult:
    status: str
    adapter: str
    model_version: str | None = None
    regression_score: float | None = None
    regression_flag: bool | None = None
    confidence: float | None = None
    overall_pattern: str | None = None
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None


def _value(metrics: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if metrics.get(alias) is not None:
            return metrics[alias]
    return None


def build_input(
    reference: dict[str, Any], current: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    missing: list[str] = []

    def model_session(session: dict[str, Any]) -> dict[str, Any]:
        mapped: dict[str, Any] = {}
        for target, aliases in METRIC_ALIASES.items():
            value = _value(session["metrics"], aliases)
            if value is None:
                missing.append(target)
            else:
                mapped[target] = value
        quality = session["quality"]
        quality_fields = (
            "camera_tracking_percent",
            "imu_capture_percent",
            "calibration_valid",
            "dropped_frame_count",
        )
        for field in quality_fields:
            if quality.get(field) is None:
                missing.append(f"quality.{field}")
        dropped_samples = quality.get("dropped_sample_count", quality.get("imu_samples_invalid"))
        if dropped_samples is None:
            missing.append("quality.dropped_sample_count")
        return {
            "session_id": session["session_id"],
            "timestamp": session["created_at"],
            "metrics": mapped,
            "quality": {
                "camera_tracking_percent": quality.get("camera_tracking_percent"),
                "imu_capture_percent": quality.get("imu_capture_percent"),
                "calibration_valid": quality.get("calibration_valid"),
                "dropped_frame_count": quality.get("dropped_frame_count"),
                "dropped_sample_count": dropped_samples,
                "warnings": quality.get("warnings", []),
            },
        }

    ref = model_session(reference)
    cur = model_session(current)
    missing = sorted(set(missing))
    if missing:
        return None, missing

    changes = {}
    for metric in METRIC_ALIASES:
        before = float(ref["metrics"][metric])
        after = float(cur["metrics"][metric])
        delta = round(after - before, 1)
        lower_is_better = metric not in {"path_inside_percent"}
        if abs(delta) < 0.05:
            direction = "stable"
        elif (delta < 0 and lower_is_better) or (delta > 0 and not lower_is_better):
            direction = "improved"
        else:
            direction = "declined"
        changes[metric] = {"absolute_change": delta, "direction": direction}

    reliable = bool(ref["quality"]["calibration_valid"] and cur["quality"]["calibration_valid"])
    return {
        "participant_id": current["username"],
        "task_type": current["task"]["type"],
        "reference_session": ref,
        "current_session": cur,
        "changes": changes,
        "comparison_reliability": "reliable" if reliable else "unreliable",
        "permitted_next_steps": PERMITTED_STEPS,
    }, []


def _validate_response(data: Any, permitted_steps: list[str]) -> dict[str, Any]:
    required = {
        "overall_pattern",
        "observations",
        "conflicts_or_limitations",
        "possible_next_step",
        "therapist_review_required",
    }
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("response keys do not match the FreeSOLO contract")
    if data["overall_pattern"] not in ALLOWED_PATTERNS:
        raise ValueError("invalid overall_pattern")
    if not isinstance(data["observations"], list) or len(data["observations"]) != 2:
        raise ValueError("observations must contain exactly two entries")
    for observation in data["observations"]:
        if not isinstance(observation, dict) or set(observation) != {
            "statement",
            "metric_keys",
        }:
            raise ValueError("invalid observation shape")
        if not isinstance(observation["statement"], str) or not observation["metric_keys"]:
            raise ValueError("invalid observation values")
        if not set(observation["metric_keys"]).issubset(METRIC_ALIASES):
            raise ValueError("observation contains an unknown metric key")
    if not isinstance(data["conflicts_or_limitations"], list) or not all(
        isinstance(item, str) for item in data["conflicts_or_limitations"]
    ):
        raise ValueError("conflicts_or_limitations must be a string list")
    if data["possible_next_step"] not in permitted_steps:
        raise ValueError("possible_next_step is not permitted")
    if data["therapist_review_required"] is not True:
        raise ValueError("therapist_review_required must be true")
    return data


class FreeSoloAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def analyze(self, reference: dict[str, Any] | None, current: dict[str, Any]) -> AnalysisResult:
        if reference is None:
            return AnalysisResult("unavailable", "freesolo_http", error_code="no_reference_session")
        model_input, missing = build_input(reference, current)
        if missing:
            return AnalysisResult(
                "unavailable",
                "freesolo_http",
                model_version=self.settings.freesolo_model or None,
                error_code="missing_required_metrics",
                error_detail=", ".join(missing),
            )
        if self.settings.freesolo_mode == "disabled":
            return AnalysisResult("unavailable", "disabled", error_code="adapter_disabled")
        if self.settings.freesolo_mode == "mock":
            return self._mock(model_input)
        if not self.settings.freesolo_model or not self.settings.freesolo_api_key:
            return AnalysisResult(
                "unavailable",
                "freesolo_http",
                model_version=self.settings.freesolo_model or None,
                error_code="model_not_configured",
            )
        return self._http(model_input)

    def _http(self, model_input: dict[str, Any]) -> AnalysisResult:
        response_schema = json.loads(json.dumps(RESPONSE_SCHEMA))
        response_schema["properties"]["possible_next_step"]["enum"] = model_input[
            "permitted_next_steps"
        ]
        payload = {
            "model": self.settings.freesolo_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(model_input, separators=(",", ":"))},
            ],
            "temperature": 0,
            "max_tokens": 700,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "rehabtrace_summary",
                    "schema": response_schema,
                    "strict": True,
                },
            },
        }
        request = urllib.request.Request(
            self.settings.freesolo_endpoint,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.freesolo_api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.settings.freesolo_timeout_seconds
            ) as response:
                envelope = json.loads(response.read())
            content = envelope["choices"][0]["message"]["content"]
            output = _validate_response(json.loads(content), model_input["permitted_next_steps"])
        except (urllib.error.URLError, TimeoutError) as exc:
            return AnalysisResult(
                "error",
                "freesolo_http",
                self.settings.freesolo_model,
                error_code="service_request_failed",
                error_detail=str(exc),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return AnalysisResult(
                "error",
                "freesolo_http",
                self.settings.freesolo_model,
                error_code="invalid_model_response",
                error_detail=str(exc),
            )
        pattern = output["overall_pattern"]
        return AnalysisResult(
            "completed",
            "freesolo_http",
            self.settings.freesolo_model,
            regression_flag=pattern == "declined",
            overall_pattern=pattern,
            result=output,
        )

    def _mock(self, model_input: dict[str, Any]) -> AnalysisResult:
        directions = [change["direction"] for change in model_input["changes"].values()]
        improved = directions.count("improved")
        declined = directions.count("declined")
        pattern = (
            "mixed"
            if improved and declined
            else "declined"
            if declined
            else "improved"
            if improved
            else "stable"
        )
        output = {
            "overall_pattern": pattern,
            "observations": [
                {
                    "statement": "Development-only model simulation.",
                    "metric_keys": ["mean_deviation_mm"],
                },
                {
                    "statement": "No production prediction was generated.",
                    "metric_keys": ["completion_time_seconds"],
                },
            ],
            "conflicts_or_limitations": [
                "These results describe measured performance on this standardized task only."
            ],
            "possible_next_step": model_input["permitted_next_steps"][0],
            "therapist_review_required": True,
        }
        return AnalysisResult(
            "completed",
            "development_mock",
            "development-mock-1",
            regression_score=float(declined) / len(directions),
            regression_flag=pattern == "declined",
            confidence=0.0,
            overall_pattern=pattern,
            result=output,
        )
