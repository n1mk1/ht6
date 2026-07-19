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

EXPLAIN_VERSION = "praxis-explain-1.1.0"

BASE = os.path.expanduser("~/steadyeye")
LLAMA_ROOT = os.path.join(BASE, "vendor", "qnx-root")
# Environment variables can override the app-local QNX package/model defaults.
LLAMA_BIN = os.environ.get(
    "PRAXIS_LLAMA_BIN", os.path.join(LLAMA_ROOT, "usr", "bin", "llama-completion"))
LLAMA_MODEL = os.environ.get(
    "PRAXIS_LLAMA_MODEL", os.path.join(BASE, "models", "SmolVLM-256M-Instruct-Q8_0.gguf"))
LLAMA_TIMEOUT_S = float(os.environ.get("PRAXIS_LLAMA_TIMEOUT_S", "45"))
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
    image_quality = obj.get("image_quality") or {}
    if image_quality.get("ok"):
        if image_quality.get("classification") == "valid":
            parts.append("The on-device image-quality model accepted the final capture.")
        else:
            parts.append("The on-device image-quality model recommends repeating the capture.")
    parts.append("These are prototype task-performance measures, not a clinical "
                 "or diagnostic assessment.")
    return " ".join(parts)


# ------------------------------------------------------------- llama.cpp
_PROMPT = """Select the clearest explanation for this rehabilitation tracing
session. Return the index of exactly one supplied candidate. The output grammar
enforces the allowed index.

DECISION FACTS:
%s

CANDIDATE STYLES:
%s
"""


def _concise_candidate(obj):
    s, b = obj["scores"], obj["bands"]
    pa, ps = obj["percentiles"]["accuracy"], obj["percentiles"]["stability"]
    parts = [
        f"Accuracy scored {s['accuracy']} ({b['accuracy']}), with "
        f"{_pct_phrase(pa).lower()}.",
        f"Stability scored {s['stability']} ({b['stability']}), with "
        f"{_pct_phrase(ps).lower()}.",
    ]
    image_quality = obj.get("image_quality") or {}
    if image_quality.get("ok"):
        action = ("accepted the final capture" if
                  image_quality.get("classification") == "valid" else
                  "recommends repeating the final capture")
        parts.append(f"The on-device image-quality model {action}.")
    parts.append("These are prototype task-performance measures, not a clinical "
                 "or diagnostic assessment.")
    return " ".join(parts)


def _candidate_summaries(obj):
    candidates = [template_summary(obj), _concise_candidate(obj)]
    return list(dict.fromkeys(candidates))


def _run_llama(obj):
    if not (LLAMA_BIN and LLAMA_MODEL and os.path.exists(LLAMA_BIN)
            and os.path.exists(LLAMA_MODEL)):
        return None
    candidates = _candidate_summaries(obj)
    image_quality = obj.get("image_quality") or {}
    decision_facts = {
        "accuracy_band": obj["bands"].get("accuracy"),
        "stability_band": obj["bands"].get("stability"),
        "image_quality": image_quality.get("classification"),
        "quality_warnings": obj.get("quality_warnings") or [],
    }
    styles = ["detailed metrics and quality", "concise scores and quality"]
    prompt = _PROMPT % (json.dumps(decision_facts), json.dumps(styles))
    selection_schema = json.dumps({
        "type": "object",
        "properties": {"selection": {"type": "integer",
                                      "enum": list(range(len(candidates)))}},
        "required": ["selection"],
        "additionalProperties": False,
    }, separators=(",", ":"))
    try:
        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = LLAMA_LIBS
        env["GGML_BACKEND_PATH"] = LLAMA_CPU_BACKEND
        p = subprocess.run(
            [LLAMA_BIN, "-m", LLAMA_MODEL, "-p", prompt, "-n", "12",
             "--temp", "0.0", "-no-cnv", "-t", "3", "--prio", "-1",
             "--poll", "0", "-c", "512", "--no-display-prompt",
             "--no-warmup", "-fit", "off", "--simple-io",
             "-lv", "0", "--no-perf", "--json-schema", selection_schema],
            capture_output=True, text=True, timeout=LLAMA_TIMEOUT_S, env=env)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = p.stdout
    decoder = json.JSONDecoder()
    selections = []
    for match in re.finditer(r"\{", out):
        try:
            candidate, _ = decoder.raw_decode(out[match.start():])
        except (json.JSONDecodeError, ValueError):
            continue
        selection = candidate.get("selection") if isinstance(candidate, dict) else None
        if isinstance(selection, int) and 0 <= selection < len(candidates):
            selections.append(selection)
    return candidates[selections[-1]] if selections else None


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
