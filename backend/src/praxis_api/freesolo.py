from __future__ import annotations

import json
import math
import re
import ssl
import urllib.error
import urllib.request

import certifi

# Use certifi's CA bundle so HTTPS to the FreeSOLO endpoint works on Python
# builds whose OpenSSL can't see the system root store (common on macOS).
_TLS_CONTEXT = ssl.create_default_context(cafile=certifi.where())
from dataclasses import dataclass
from typing import Any

from .config import Settings

CONTRACT_VERSION = "praxis-freesolo-2.0"
METRIC_SPECS: dict[str, dict[str, Any]] = {
    "accuracy_score": {"better": "higher", "tolerance": 3.0, "source": ("scores", "accuracy")},
    "stability_score": {"better": "higher", "tolerance": 3.0, "source": ("scores", "stability")},
    "coverage_pct": {"better": "higher", "tolerance": 3.0, "source": ("metrics", "coverage_pct")},
    "mean_dev_mm": {"better": "lower", "tolerance": 0.3, "source": ("metrics", "mean_dev_mm")},
    "max_dev_mm": {"better": "lower", "tolerance": 0.5, "source": ("metrics", "max_dev_mm")},
    "rms_dev_mm": {"better": "lower", "tolerance": 0.3, "source": ("metrics", "rms_dev_mm")},
    "completion_time_seconds": {
        "better": "lower",
        "tolerance": 1.0,
        "source": ("metrics", "completion_time_seconds"),
        "contextual": True,
    },
    "tremor_rms_deg_s": {
        "better": "lower",
        "tolerance": 0.3,
        "source": ("metrics", "tremor_rms_deg_s"),
    },
    "peak_angular_velocity_deg_s": {
        "better": "lower",
        "tolerance": 3.0,
        "source": ("metrics", "peak_angular_velocity_deg_s"),
        "contextual": True,
    },
}
METRIC_KEYS = tuple(METRIC_SPECS)
ALLOWED_PATTERNS = {"improved", "declined", "stable", "mixed", "unreliable"}
NEXT_STEPS = {
    "improved": "Continue monitoring performance at future sessions.",
    "declined": "Collect another compatible session before drawing a broader conclusion.",
    "stable": "Repeat the same standardized task at the next planned session.",
    "mixed": "Review the accuracy-versus-stability tradeoff with the participant.",
    "unreliable": "Repeat the session after resolving the recorded data-quality issue.",
}
PERMITTED_STEPS = list(NEXT_STEPS.values())
SYSTEM_PROMPT = "\n".join(
    [
        "You explain deterministic changes between two compatible Praxis path-tracing "
        "sessions for therapist review.",
        "The input already contains authoritative scores, physical measurements, quality "
        "fields, and change directions. Do not calculate new values, choose a different "
        "baseline, or infer causes.",
        "Return only one JSON object matching the supplied schema, with exactly two observations.",
        "Cover both accuracy_score and stability_score across the observations. Supporting "
        "metric keys may be cited when they reinforce the same direction.",
        "Use only metric keys present in changes. Every number in an observation must exactly "
        "match a number in the input.",
        "overall_pattern is determined by accuracy_score and stability_score: opposing "
        "directions are mixed; one directional score with the other stable uses that "
        "direction; both stable is stable.",
        "Completion time and peak angular velocity are contextual and do not determine "
        "overall_pattern.",
        "If comparison_reliability is unreliable, overall_pattern must be unreliable, do not "
        "claim improvement or decline, and explain a supplied reliability reason.",
        "possible_next_step must exactly match the appropriate option already included in "
        "permitted_next_steps.",
        "therapist_review_required must always be true.",
        "Never diagnose, claim recovery or neurological improvement, infer why values "
        "changed, recommend treatment, or compare against a population.",
    ]
)
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
UNSAFE_RE = re.compile(
    r"\b(diagnos(?:e[sd]?|ing)|recover\w*|remission|relaps\w*|disease|stroke|"
    r"therapy (?:is |was )?work\w*|treatment should|motor function has improved|"
    r"neurological (?:recovery|improvement)|caused by|due to (?:fatigue|medication|practice))\b",
    re.I,
)
CHANGE_CLAIM_RE = re.compile(
    r"\b(improv\w*|declin\w*|wors\w*|better|less stable|more accurate)\b", re.I
)
IMPROVED_RE = re.compile(
    r"\b(improv\w*|better|more accurate|steadier|decreased error|lower error)\b", re.I
)
DECLINED_RE = re.compile(r"\b(declin\w*|wors\w*|less accurate|less stable|higher error)\b", re.I)
STABLE_RE = re.compile(r"\b(stable|similar|little change|within the stability threshold)\b", re.I)
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])-?\d+(?:\.\d+)?")


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


def _compatibility_key(session: dict[str, Any]) -> tuple[str, str, str, str]:
    task = session["task"]
    return (
        str(task.get("type", "")),
        str(task.get("version", "")),
        str(task.get("difficulty", "")),
        str(task.get("hand", task.get("dominant_hand", ""))),
    )


def _source_value(session: dict[str, Any], group: str, key: str) -> Any:
    value = session.get(group, {}).get(key)
    if value is None and group == "scores":
        value = session.get("metrics", {}).get(f"{key}_score")
    return value


def _model_session(session: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    scores: dict[str, float] = {}
    metrics: dict[str, float] = {}
    for target, spec in METRIC_SPECS.items():
        group, source = spec["source"]
        value = _source_value(session, group, source)
        if value is None:
            missing.append(target)
            continue
        if group == "scores":
            scores[source] = float(value)
        else:
            metrics[source] = float(value)

    quality = session.get("quality", {})
    quality_fields = (
        "calibration_valid",
        "n_ref_slices",
        "n_scored_slices",
        "imu_samples_received",
        "imu_samples_invalid",
        "imu_rate_hz",
    )
    for field in quality_fields:
        if quality.get(field) is None:
            missing.append(f"quality.{field}")
    return {
        "session_id": session["session_id"],
        "timestamp": session["created_at"],
        "task": session["task"],
        "score_version": session.get("scores", {}).get("version"),
        "scores": scores,
        "metrics": metrics,
        "quality": {field: quality.get(field) for field in quality_fields}
        | {"warnings": quality.get("warnings", [])},
    }


def _flat(session: dict[str, Any]) -> dict[str, float]:
    return {
        "accuracy_score": session["scores"]["accuracy"],
        "stability_score": session["scores"]["stability"],
        **session["metrics"],
    }


def _changes(reference: dict[str, Any], current: dict[str, Any]) -> dict[str, dict[str, Any]]:
    before_values = _flat(reference)
    after_values = _flat(current)
    changes: dict[str, dict[str, Any]] = {}
    for key, spec in METRIC_SPECS.items():
        before = float(before_values[key])
        after = float(after_values[key])
        delta = round(after - before, 2)
        if math.isclose(delta, 0.0, abs_tol=float(spec["tolerance"])):
            direction = "stable"
        elif (delta > 0) == (spec["better"] == "higher"):
            direction = "improved"
        else:
            direction = "declined"
        changes[key] = {
            "reference": round(before, 2),
            "current": round(after, 2),
            "absolute_change": delta,
            "direction": direction,
            "contextual": bool(spec.get("contextual", False)),
        }
    return changes


def _reliability_reasons(reference: dict[str, Any], current: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if _compatibility_key(reference) != _compatibility_key(current):
        reasons.append("task_mismatch")
    if reference.get("score_version") != current.get("score_version"):
        reasons.append("score_version_mismatch")
    for session in (reference, current):
        quality = session["quality"]
        if not quality["calibration_valid"]:
            reasons.append("calibration_invalid")
        if int(quality["n_ref_slices"]) <= 0 or int(quality["n_scored_slices"]) <= 0:
            reasons.append("vision_samples_missing")
        if int(quality["imu_samples_received"]) <= 0:
            reasons.append("imu_samples_missing")
        if any(
            str(warning).startswith(("capture_", "vision_no", "scale_calibration"))
            for warning in quality["warnings"]
        ):
            reasons.append("capture_warning")
    return sorted(set(reasons))


def build_input(
    reference: dict[str, Any], current: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    missing: list[str] = []
    ref = _model_session(reference, missing)
    cur = _model_session(current, missing)
    missing = sorted(set(missing))
    if missing:
        return None, missing
    reasons = _reliability_reasons(ref, cur)
    participant_id = current.get("username") or current.get("user", {}).get("username")
    if not participant_id:
        return None, ["username"]
    return {
        "contract_version": CONTRACT_VERSION,
        "participant_id": participant_id,
        "reference_session": ref,
        "current_session": cur,
        "changes": _changes(ref, cur),
        "comparison_reliability": "unreliable" if reasons else "reliable",
        "reliability_reasons": reasons,
        "permitted_next_steps": PERMITTED_STEPS,
    }, []


def _expected_pattern(model_input: dict[str, Any]) -> str:
    if model_input["comparison_reliability"] != "reliable":
        return "unreliable"
    directions = {
        model_input["changes"][key]["direction"] for key in ("accuracy_score", "stability_score")
    }
    if "improved" in directions and "declined" in directions:
        return "mixed"
    if "improved" in directions:
        return "improved"
    if "declined" in directions:
        return "declined"
    return "stable"


def _input_numbers(model_input: dict[str, Any]) -> set[float]:
    numbers: set[float] = set()
    for session_name in ("reference_session", "current_session"):
        for group in ("scores", "metrics", "quality"):
            for value in model_input[session_name][group].values():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    numbers.add(round(float(value), 2))
    for change in model_input["changes"].values():
        numbers.update(
            round(float(change[key]), 2) for key in ("reference", "current", "absolute_change")
        )
    return numbers


def _validate_response(data: Any, model_input: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != {
        "overall_pattern",
        "observations",
        "conflicts_or_limitations",
        "possible_next_step",
        "therapist_review_required",
    }:
        raise ValueError("response keys do not match the FreeSOLO v2 contract")
    expected_pattern = _expected_pattern(model_input)
    if data["overall_pattern"] != expected_pattern:
        raise ValueError(f"incorrect overall_pattern; expected {expected_pattern}")
    observations = data["observations"]
    if not isinstance(observations, list) or len(observations) != 2:
        raise ValueError("observations must contain exactly two entries")
    cited: set[str] = set()
    valid_numbers = _input_numbers(model_input)
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != {"statement", "metric_keys"}:
            raise ValueError("invalid observation shape")
        if not isinstance(observation["statement"], str) or not observation["metric_keys"]:
            raise ValueError("invalid observation values")
        if not set(observation["metric_keys"]).issubset(METRIC_KEYS):
            raise ValueError("observation contains an unknown metric key")
        cited.update(observation["metric_keys"])
        for raw in NUMBER_RE.findall(observation["statement"]):
            value = round(float(raw), 2)
            if not any(math.isclose(value, valid, abs_tol=0.011) for valid in valid_numbers):
                raise ValueError(f"observation contains an ungrounded number: {raw}")
        directions = {
            model_input["changes"][key]["direction"]
            for key in observation["metric_keys"]
            if not model_input["changes"][key].get("contextual")
        }
        statement = observation["statement"]
        if expected_pattern == "unreliable":
            if IMPROVED_RE.search(statement) or DECLINED_RE.search(statement):
                raise ValueError("unreliable comparison contains a performance claim")
        elif directions == {"improved"} and not IMPROVED_RE.search(statement):
            raise ValueError("observation does not describe the cited improvement")
        elif directions == {"declined"} and not DECLINED_RE.search(statement):
            raise ValueError("observation does not describe the cited decline")
        elif directions == {"stable"} and not STABLE_RE.search(statement):
            raise ValueError("observation does not describe the cited stable result")
    if not {"accuracy_score", "stability_score"}.issubset(cited):
        raise ValueError("observations must cover accuracy_score and stability_score")
    conflicts = data["conflicts_or_limitations"]
    if (
        not isinstance(conflicts, list)
        or not 1 <= len(conflicts) <= 2
        or not all(isinstance(item, str) for item in conflicts)
    ):
        raise ValueError("conflicts_or_limitations must contain one or two strings")
    full_text = json.dumps(data)
    if UNSAFE_RE.search(full_text):
        raise ValueError("response contains unsafe clinical language")
    if expected_pattern == "unreliable":
        reasons = model_input["reliability_reasons"]
        limitations_text = " ".join(conflicts).lower()
        reason_terms = {
            "calibration_invalid": "calibration",
            "vision_samples_missing": "vision",
            "imu_samples_missing": "imu",
            "capture_warning": "capture",
            "task_mismatch": "task",
            "score_version_mismatch": "score version",
        }
        if not any(reason_terms[reason] in limitations_text for reason in reasons):
            raise ValueError("response does not explain a recorded reliability reason")
    expected_step = NEXT_STEPS[expected_pattern]
    if data["possible_next_step"] != expected_step:
        raise ValueError(f"incorrect possible_next_step; expected {expected_step}")
    if data["therapist_review_required"] is not True:
        raise ValueError("therapist_review_required must be true")
    return data


class FreeSoloAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def analyze(self, reference: dict[str, Any] | None, current: dict[str, Any]) -> AnalysisResult:
        if reference is None:
            return AnalysisResult(
                "unavailable", "freesolo_http_v2", error_code="no_reference_session"
            )
        model_input, missing = build_input(reference, current)
        if missing:
            return AnalysisResult(
                "unavailable",
                "freesolo_http_v2",
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
                "freesolo_http_v2",
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
                    "name": "praxis_session_analysis_v2",
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
                request, timeout=self.settings.freesolo_timeout_seconds, context=_TLS_CONTEXT
            ) as response:
                envelope = json.loads(response.read())
            content = envelope["choices"][0]["message"]["content"]
            output = _validate_response(json.loads(content), model_input)
        except (urllib.error.URLError, TimeoutError) as error:
            return AnalysisResult(
                "error",
                "freesolo_http_v2",
                self.settings.freesolo_model,
                error_code="service_request_failed",
                error_detail=str(error),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            return AnalysisResult(
                "error",
                "freesolo_http_v2",
                self.settings.freesolo_model,
                error_code="invalid_model_response",
                error_detail=str(error),
            )
        pattern = output["overall_pattern"]
        return AnalysisResult(
            "completed",
            "freesolo_http_v2",
            self.settings.freesolo_model,
            regression_flag=pattern == "declined",
            overall_pattern=pattern,
            result=output,
        )

    def _mock(self, model_input: dict[str, Any]) -> AnalysisResult:
        pattern = _expected_pattern(model_input)
        output = {
            "overall_pattern": pattern,
            "observations": [
                {
                    "statement": (
                        "Development-only accuracy analysis; no production model response "
                        "was generated."
                    ),
                    "metric_keys": ["accuracy_score"],
                },
                {
                    "statement": (
                        "Development-only stability analysis; no production model response "
                        "was generated."
                    ),
                    "metric_keys": ["stability_score"],
                },
            ],
            "conflicts_or_limitations": [
                "This is a development simulation and not a production model result."
            ],
            "possible_next_step": NEXT_STEPS[pattern],
            "therapist_review_required": True,
        }
        return AnalysisResult(
            "completed",
            "development_mock",
            "development-mock-v2",
            regression_flag=pattern == "declined",
            confidence=0.0,
            overall_pattern=pattern,
            result=output,
        )
