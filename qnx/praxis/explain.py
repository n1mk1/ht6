"""Praxis explainability layer — turns the finished deterministic result into a
plain-language summary. It NEVER computes or alters a metric.

Order of operations (enforced by the caller): acquisition -> scoring ->
stratification/percentile -> THEN explain(). The LLM (llama.cpp) is optional:
its output is schema-constrained, every number is validated against the source
object, and ANY failure/timeout/mismatch falls back to a deterministic template.
"""
import json
import os
import re
import subprocess
import time

EXPLAIN_VERSION = "praxis-explain-1.2.0"

BASE = os.path.expanduser("~/steadyeye")
LLAMA_ROOT = os.path.join(BASE, "vendor", "qnx-root")
# Environment variables can override the app-local QNX package/model defaults.
LLAMA_BIN = os.environ.get(
    "PRAXIS_LLAMA_BIN", os.path.join(LLAMA_ROOT, "usr", "bin", "llama-completion"))
LLAMA_MODEL = os.environ.get(
    "PRAXIS_LLAMA_MODEL",
    os.path.join(BASE, "models", "qwen2.5-0.5b-instruct-q4_k_m.gguf"))
LLAMA_TIMEOUT_S = float(os.environ.get("PRAXIS_LLAMA_TIMEOUT_S", "75"))
LLAMA_LIBS = os.pathsep.join([
    os.path.join(LLAMA_ROOT, "usr", "lib", "llama.cpp"),
    os.path.join(LLAMA_ROOT, "usr", "lib"), "/usr/lib", "/lib",
])
LLAMA_CPU_BACKEND = os.environ.get(
    "PRAXIS_LLAMA_BACKEND",
    os.path.join(LLAMA_ROOT, "usr", "lib", "llama.cpp", "libggml-cpu.so"))


# --------------------------------------------------------- structured input
def build_input(task, scores, bands, percentiles, metrics, quality_warnings,
                image_quality=None):
    """Assemble the validated structured object handed to the explainer."""
    return {
        "task": task,
        "scores": {"accuracy": scores.get("accuracy"),
                   "stability": scores.get("stability")},
        "bands": {"accuracy": bands.get("accuracy"),
                  "stability": bands.get("stability")},
        "percentiles": percentiles,
        "metrics": {
            "coverage_pct": metrics.get("coverage_pct"),
            "mean_dev_mm": metrics.get("mean_dev_mm"),
            "completion_time_seconds": metrics.get("completion_time_seconds"),
            "gyro_rms_deg_s": metrics.get("gyro_rms_deg_s"),
            "tremor_rms_deg_s": metrics.get("tremor_rms_deg_s"),
        },
        "image_quality": image_quality or {"ok": False, "error": "unavailable"},
        "quality_warnings": quality_warnings or [],
    }


# -------------------------------------------------------- number validation
def _allowed_numbers(obj):
    """Every numeric value the summary is allowed to mention."""
    allowed = set()

    def add(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            allowed.add(round(float(v), 2))

    s = obj["scores"]; add(s["accuracy"]); add(s["stability"])
    for m in obj["metrics"].values():
        add(m)
    for meas in obj["percentiles"].values():
        add(meas.get("percentile"))
        add(meas.get("sample_count"))
    image_quality = obj.get("image_quality") or {}
    add(image_quality.get("valid_probability"))
    add(image_quality.get("inference_ms"))
    add(image_quality.get("threshold"))
    t = obj.get("task") or {}
    add(t.get("difficulty"))
    return allowed


def validate_summary(text, obj):
    """Every number in `text` must correspond to an allowed source number, and
    the exact scores/bands must appear. Returns True if the summary is faithful."""
    if not isinstance(text, str) or not text.strip() or len(text) > 1200:
        return False
    allowed = _allowed_numbers(obj)
    percentile_values = set()
    for measurement in obj.get("percentiles", {}).values():
        value = measurement.get("percentile")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            percentile_values.add(round(float(value), 2))
    percentile_mentions = re.findall(
        r"(?i)(?:percentile\s*:?\s*(-?\d+(?:\.\d+)?)|"
        r"(-?\d+(?:\.\d+)?)(?:st|nd|rd|th)?\s+percentile)", text)
    for before, after in percentile_mentions:
        value = round(float(before or after), 2)
        if not any(abs(value - actual) < 0.05 for actual in percentile_values):
            return False
    # A leading '-' only counts as negative when not preceded by a word char or
    # dot, so ranges like "0-100" tokenize as 0 and 100 (not -100).
    for tok in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text):
        try:
            val = round(float(tok), 2)
        except ValueError:
            continue
        if not any(abs(val - a) < 0.05 for a in allowed):
            return False  # a number not backed by the source metrics
    if _score_sentence(obj).lower() not in text.lower():
        return False
    if DISCLAIMER.lower() not in text.lower():
        return False
    image_quality = obj.get("image_quality") or {}
    if image_quality.get("ok"):
        lower = text.lower()
        if image_quality.get("classification") == "valid":
            if "accepted" not in lower or "capture" not in lower:
                return False
        elif "repeat" not in lower or "capture" not in lower:
            return False
    forbidden = (
        "approved for medical", "therapeutic purposes", "medical advice",
        "seek treatment", "indicates a diagnosis", "recovery rate",
        "better than average", "worse than average",
        "reliable", "reliability", "successful", "successfully",
    )
    if any(phrase in text.lower() for phrase in forbidden):
        return False
    return True


# --------------------------------------------------------- template summary
def _pct_phrase(meas):
    p = meas.get("percentile")
    if p is None:
        return "Percentile unavailable"
    label = meas.get("label") or "reference-set percentile"
    return f"{p}th percentile ({label})"


DISCLAIMER = ("These are prototype task-performance measures, not a clinical "
              "or diagnostic assessment.")


def _score_sentence(obj):
    s, b = obj["scores"], obj["bands"]
    return (f"Accuracy scored {s['accuracy']} ({b['accuracy']}) and stability "
            f"scored {s['stability']} ({b['stability']}).")


def template_summary(obj):
    """Deterministic, always-valid summary. Repeats scores/bands/percentiles and
    the main contributing factors using only supplied facts."""
    s, b, m = obj["scores"], obj["bands"], obj["metrics"]
    pa, ps = obj["percentiles"]["accuracy"], obj["percentiles"]["stability"]
    parts = []
    parts.append(_score_sentence(obj))
    parts.append(
        f"Accuracy percentile: {_pct_phrase(pa)}. "
        f"Stability percentile: {_pct_phrase(ps)}.")
    factors = []
    if m.get("mean_dev_mm") is not None:
        factors.append(f"mean spatial error {m['mean_dev_mm']} mm")
    if m.get("coverage_pct") is not None:
        factors.append(f"{m['coverage_pct']}% pattern coverage")
    if m.get("tremor_rms_deg_s") is not None:
        factors.append(f"tremor {m['tremor_rms_deg_s']} deg/s")
    if m.get("completion_time_seconds") is not None:
        factors.append(f"completion time {m['completion_time_seconds']} s")
    if factors:
        parts.append("Main factors: " + ", ".join(factors) + ".")
    if obj.get("quality_warnings"):
        parts.append("Quality notes: " + ", ".join(obj["quality_warnings"]) + ".")
    image_quality = obj.get("image_quality") or {}
    if image_quality.get("ok"):
        if image_quality.get("classification") == "valid":
            parts.append("The on-device image-quality model accepted the final capture.")
        else:
            parts.append("The on-device image-quality model recommends repeating the capture.")
    parts.append(DISCLAIMER)
    return " ".join(parts)


# ------------------------------------------------------------- llama.cpp
_PROMPT = """<|im_start|>system
You write factual plain-language analysis for one rehabilitation tracing session.
Use only supplied facts. Never provide diagnosis, medical advice, treatment
guidance, recovery claims, or unsupported comparisons.<|im_end|>
<|im_start|>user
Write JSON containing one concise analysis sentence of 20 to 45 words.

Requirements:
- Interpret one to three supplied measurements without judging health.
- State measurement names and exact values neutrally; do not label a value as
  high, low, good, bad, normal, abnormal, acceptable, or minimal.
- Use this style: "Mean spatial error was <value> mm, pattern coverage was
  <value>%, and tremor RMS was <value> deg/s." Select only available facts.
- Do not add an explanation after reporting the measurements.
- Do not repeat the scores, bands, image decision, or limitation; they are
  added separately by deterministic code.
- Do not say a value indicates or suggests anything.
- Do not invent numbers, causes, trends, success claims, or comparisons.
- Do not repeat yourself.

Session facts:
{facts}
<|im_end|>
<|im_start|>assistant
"""


def _image_quality_statement(obj):
    quality = obj.get("image_quality") or {}
    if not quality.get("ok"):
        return "The image-quality model was unavailable; deterministic scores were preserved."
    if quality.get("classification") == "valid":
        return "The on-device image-quality model accepted the final capture."
    return "The on-device image-quality model recommends repeating the final capture."


def _generation_facts(obj):
    return {
        "mean_spatial_error_mm": obj["metrics"].get("mean_dev_mm"),
        "pattern_coverage_pct": obj["metrics"].get("coverage_pct"),
        "tremor_rms_deg_s": obj["metrics"].get("tremor_rms_deg_s"),
        "completion_time_s": obj["metrics"].get("completion_time_seconds"),
        "quality_warnings": obj.get("quality_warnings") or [],
    }


def _validate_analysis(analysis, obj):
    if not isinstance(analysis, str) or not 70 <= len(analysis.strip()) <= 500:
        return False
    lower = analysis.lower()
    unsupported = (
        "acceptable", "within limits", "minimal", "normal", "abnormal",
        "indicat", "suggest", "successful", "reliable", "consistent",
        "patient", "position", "movement", "slight", "substantial",
        "good", "bad", "excellent", "poor", "high", "low", "moderate",
    )
    if any(term in lower for term in unsupported):
        return False
    without_decimals = re.sub(r"(?<=\d)\.(?=\d)", "", analysis)
    if len(re.findall(r"[.!?](?:\s|$)", without_decimals)) > 2:
        return False
    framed = " ".join((_score_sentence(obj), analysis.strip(),
                       _image_quality_statement(obj), DISCLAIMER))
    return validate_summary(framed, obj)


def _run_llama(obj):
    if not (LLAMA_BIN and LLAMA_MODEL and os.path.exists(LLAMA_BIN)
            and os.path.exists(LLAMA_MODEL)):
        return None
    prompt = _PROMPT.format(
        facts=json.dumps(_generation_facts(obj), separators=(",", ":")))
    summary_schema = json.dumps({
        "type": "object",
        "properties": {"analysis": {"type": "string", "minLength": 70,
                                       "maxLength": 500}},
        "required": ["analysis"],
        "additionalProperties": False,
    }, separators=(",", ":"))
    try:
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = LLAMA_LIBS
        env["GGML_BACKEND_PATH"] = LLAMA_CPU_BACKEND
        p = subprocess.run(
            [LLAMA_BIN, "-m", LLAMA_MODEL, "-p", prompt, "-n", "120",
             "--temp", "0.2", "--top-p", "0.9", "-no-cnv", "-t", "3",
             "--prio", "-1", "--poll", "0", "-c", "1024", "--no-display-prompt",
             "--no-warmup", "-fit", "off", "--simple-io",
             "--repeat-penalty", "1.12", "--repeat-last-n", "128",
             "-lv", "0", "--no-perf", "--json-schema", summary_schema],
            capture_output=True, text=True, timeout=LLAMA_TIMEOUT_S, env=env)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = p.stdout
    decoder = json.JSONDecoder()
    analyses = []
    for match in re.finditer(r"\{", out):
        try:
            candidate, _ = decoder.raw_decode(out[match.start():])
        except (json.JSONDecodeError, ValueError):
            continue
        analysis = candidate.get("analysis") if isinstance(candidate, dict) else None
        if isinstance(analysis, str):
            analyses.append(analysis.strip())
    if not analyses or not _validate_analysis(analyses[-1], obj):
        return None
    return " ".join((_score_sentence(obj), analyses[-1],
                     _image_quality_statement(obj), DISCLAIMER))


def explain(obj):
    """Return {summary, source, validated, explain_version}. Tries llama.cpp,
    validates it, and falls back to the deterministic template on any problem."""
    started = time.monotonic()
    summary = _run_llama(obj)
    inference_ms = round((time.monotonic() - started) * 1000, 1)
    if summary and validate_summary(summary, obj):
        return {"summary": summary.strip(), "source": "llama.cpp",
                "validated": True, "explain_version": EXPLAIN_VERSION,
                "model": os.path.basename(LLAMA_MODEL),
                "inference_ms": inference_ms}
    return {"summary": template_summary(obj), "source": "template",
            "validated": True, "explain_version": EXPLAIN_VERSION,
            "model": None, "inference_ms": inference_ms}
