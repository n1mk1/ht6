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

EXPLAIN_VERSION = "praxis-explain-1.0.0"

# llama.cpp is optional. Configure with env; if absent we use the template.
LLAMA_BIN = os.environ.get("PRAXIS_LLAMA_BIN", "")     # e.g. ~/llama.cpp/llama-cli
LLAMA_MODEL = os.environ.get("PRAXIS_LLAMA_MODEL", "")  # path to a .gguf
LLAMA_TIMEOUT_S = float(os.environ.get("PRAXIS_LLAMA_TIMEOUT_S", "25"))


# --------------------------------------------------------- structured input
def build_input(task, scores, bands, percentiles, metrics, quality_warnings):
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
        "quality_warnings": quality_warnings or [],
    }


# -------------------------------------------------------- number validation
def _allowed_numbers(obj):
    """Every numeric value the summary is allowed to mention."""
    allowed = {0.0, 100.0}  # scale bounds ("0-100 scale") are always allowed

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
    t = obj.get("task") or {}
    add(t.get("difficulty"))
    return allowed


def validate_summary(text, obj):
    """Every number in `text` must correspond to an allowed source number, and
    the exact scores/bands must appear. Returns True if the summary is faithful."""
    allowed = _allowed_numbers(obj)
    # A leading '-' only counts as negative when not preceded by a word char or
    # dot, so ranges like "0-100" tokenize as 0 and 100 (not -100).
    for tok in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text):
        try:
            val = round(float(tok), 2)
        except ValueError:
            continue
        if not any(abs(val - a) < 0.05 for a in allowed):
            return False  # a number not backed by the source metrics
    # scores + bands must be stated exactly
    for key in ("accuracy", "stability"):
        sc = obj["scores"][key]
        if sc is not None and str(sc) not in text:
            return False
        bd = obj["bands"][key]
        if bd and bd not in text.lower():
            return False
    return True


# --------------------------------------------------------- template summary
def _pct_phrase(meas):
    p = meas.get("percentile")
    if p is None:
        return "Percentile unavailable"
    label = meas.get("label") or "reference-set percentile"
    return f"{p}th percentile ({label})"


def template_summary(obj):
    """Deterministic, always-valid summary. Repeats scores/bands/percentiles and
    the main contributing factors using only supplied facts."""
    s, b, m = obj["scores"], obj["bands"], obj["metrics"]
    pa, ps = obj["percentiles"]["accuracy"], obj["percentiles"]["stability"]
    parts = []
    parts.append(
        f"Accuracy scored {s['accuracy']} ({b['accuracy']}) and stability scored "
        f"{s['stability']} ({b['stability']}) on the Praxis 0-100 scale.")
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
    parts.append("These are prototype task-performance measures, not a clinical "
                 "or diagnostic assessment.")
    return " ".join(parts)


# ------------------------------------------------------------- llama.cpp
_PROMPT = """You are a careful assistant that explains ONE rehabilitation tracing
session. Use ONLY the facts in the JSON. Do not invent numbers, comparisons,
diagnoses, medical advice, or recovery claims. Repeat the scores, bands and
percentiles exactly. If a percentile is null, say "Percentile unavailable".
Never call a prototype score or percentile clinically validated.

Return ONLY a JSON object: {"summary": "<2-4 sentence explanation>"}

FACTS:
%s
"""


def _run_llama(obj):
    if not (LLAMA_BIN and LLAMA_MODEL and os.path.exists(LLAMA_BIN)
            and os.path.exists(LLAMA_MODEL)):
        return None
    prompt = _PROMPT % json.dumps(obj)
    try:
        p = subprocess.run(
            [LLAMA_BIN, "-m", LLAMA_MODEL, "-p", prompt, "-n", "220",
             "--temp", "0.2", "-no-cnv"],
            capture_output=True, text=True, timeout=LLAMA_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = p.stdout
    match = re.search(r"\{.*\}", out, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0)).get("summary")
    except (json.JSONDecodeError, ValueError):
        return None


def explain(obj):
    """Return {summary, source, validated, explain_version}. Tries llama.cpp,
    validates it, and falls back to the deterministic template on any problem."""
    summary = _run_llama(obj)
    if summary and validate_summary(summary, obj):
        return {"summary": summary.strip(), "source": "llama.cpp",
                "validated": True, "explain_version": EXPLAIN_VERSION}
    return {"summary": template_summary(obj), "source": "template",
            "validated": True, "explain_version": EXPLAIN_VERSION}
