#!/usr/bin/env python3
"""Praxis control server — runs ON the QNX Pi. Stdlib only.

Single-image model (no corner markers, no homography):

  live camera view -> START (calibrate IMU bias, then record IMU + timer)
  -> participant traces the printed BLUE pattern in RED ink -> STOP (stop IMU
  + timer) -> lift the pen -> CAPTURE & SCORE (one photo containing both the
  blue reference and the red trace; accuracy = per-vertical-slice pixel distance
  between the blue and red centroids; stability = IMU tremor during the run).
  Each run is tagged with the participant's username, saved locally, and (if
  BACKEND_URL is set) POSTed to the isolated webapp ingestion API.

  GET  /                     dashboard
  GET  /api/state            phase + captured blue/red polylines (pixels)
  GET  /api/imu_live         latest gyro magnitude + sample count (during run)
  POST /api/session/new      {"username": "..."}
  POST /api/preview          ensure persistent live-preview camera process
  POST /api/go               calibrate IMU bias, then start IMU recording + timer
  POST /api/stop             stop IMU recording + timer
  POST /api/score            one photo -> vertical-slice blue-vs-red scoring

  GET  /dataset              separate image-quality dataset capture UI
  GET  /api/dataset/status   30-shot plan and persisted capture progress
  POST /api/dataset/preview  dataset camera preview
  POST /api/dataset/capture  {"shot_id": N} -> labeled full-resolution BMP
"""
import csv
import json
import math
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.expanduser("~/steadyeye")
DASH = os.path.join(BASE, "dashboard")
SESSIONS = os.path.join(BASE, "sessions")
OUTBOX = os.path.join(BASE, "outbox")
IMAGE_QUALITY_DATA = os.path.join(BASE, "datasets", "image_quality", "data")
IMAGE_QUALITY_CAPTURES = os.path.join(IMAGE_QUALITY_DATA, "captures")
RT_VISION = os.path.join(BASE, "vision", "rt_vision")
IMU_PY = os.path.expanduser("~/venv/bin/python")
IMU_REC = os.path.join(BASE, "imu", "imu_recorder.py")
IMAGE_QUALITY_INFER = os.path.join(BASE, "image_quality", "infer.py")
IMAGE_QUALITY_MODEL = os.path.join(BASE, "image_quality", "model", "quality_model.json")
PORT = 8080

# Deterministic Praxis scoring / percentile / explainability (single source of
# truth, shared with the saved session and — by porting — the external web app).
sys.path.insert(0, BASE)
from praxis import score as praxis_score       # noqa: E402
from praxis import percentile as praxis_pct     # noqa: E402
from praxis import explain as praxis_explain    # noqa: E402

# Canonical task identity — must match a reference-set stratum for percentiles.
TASK = {"type": "path_tracing", "version": "mat_v1", "difficulty": 1}

# Webapp backend (on a separate computer) that stores and compares runs.
# Set BACKEND_URL to its base URL, e.g. http://192.168.1.50:8000 — the server
# POSTs each finished run to BACKEND_URL + BACKEND_RUNS_PATH. If unset or
# unreachable, the run is still saved locally to outbox/latest.json.
BACKEND_URL = os.environ.get("BACKEND_URL", "").rstrip("/")
BACKEND_RUNS_PATH = os.environ.get("BACKEND_RUNS_PATH", "/api/runs")
BACKEND_KEY = os.environ.get("BACKEND_KEY", "")   # optional X-Device-Key
DEVICE_ID = os.environ.get("DEVICE_ID", "qnx_pi_23")

SLICE_PX = 16          # vertical-slice width for accuracy scoring
# Fixed rig: camera height and mat distance never change, so px->mm is a
# ONE-TIME constant, not a per-run measurement. (Calibrated from an 80 mm purple
# bar measuring 736 px → 9.2 px/mm.) Recalibrate only if the rig moves: put the
# 80 mm bar in frame and run
#   ./vision/rt_vision score --out /tmp/s.json --scale-mm 80
# then set scale_px_per_mm here (or via the SCALE_PX_PER_MM env var).
SCALE_PX_PER_MM = float(os.environ.get("SCALE_PX_PER_MM", "9.2"))
# Stability tremor: high-pass |gyro| by subtracting a ~TREMOR_WIN_S moving
# average (the intended slow trajectory); the residual RMS is the tremor. The
# 0-100 scaling, bands and version live in praxis.score (single source of truth).
TREMOR_WIN_S = 0.3     # moving-average window (s) that defines "intended motion"

S = {
    "phase": "idle",   # idle -> recording -> stopped -> complete
    "session_id": None, "username": "",
    "imu_cal": None, "score": None,
    "t_go": None, "t_stop": None, "result": None, "error": None,
}
LOCK = threading.Lock()
CAM_LOCK = threading.Lock()   # only one rt_vision may hold the camera at a time
PROCS = {}
CAMERA = {"path": None}

# A deliberately small, balanced dataset for a binary image-quality model.
# Accurate and inaccurate traces are both valid: this model decides whether a
# frame is usable by the deterministic scorer, not how well the trace was drawn.
IMAGE_QUALITY_PLAN = [
    {"id": 1, "label": "valid", "condition": "accurate",
     "instruction": "Draw an accurate trace. Keep the full sheet clear and centered."},
    {"id": 2, "label": "valid", "condition": "accurate",
     "instruction": "Draw another accurate trace with the normal camera and lighting setup."},
    {"id": 3, "label": "valid", "condition": "accurate",
     "instruction": "Draw an accurate trace. Shift the sheet slightly left, but keep all of it visible."},
    {"id": 4, "label": "valid", "condition": "accurate",
     "instruction": "Draw an accurate trace. Shift the sheet slightly right, but keep all of it visible."},
    {"id": 5, "label": "valid", "condition": "accurate",
     "instruction": "Draw an accurate trace in normal light with the full sheet visible."},
    {"id": 6, "label": "valid", "condition": "inaccurate",
     "instruction": "Draw a clearly inaccurate trace. Keep the image sharp and correctly framed."},
    {"id": 7, "label": "valid", "condition": "inaccurate",
     "instruction": "Draw above the reference path. Keep the sheet clear and centered."},
    {"id": 8, "label": "valid", "condition": "inaccurate",
     "instruction": "Draw below the reference path. Keep the sheet clear and centered."},
    {"id": 9, "label": "valid", "condition": "inaccurate",
     "instruction": "Draw an uneven or shaky trace. Keep the final image sharp and unobstructed."},
    {"id": 10, "label": "valid", "condition": "inaccurate",
     "instruction": "Draw an incomplete-looking but visible trace. Keep the entire target in frame."},
    {"id": 11, "label": "invalid", "condition": "blur",
     "instruction": "Move the sheet left and right continuously while you press Capture."},
    {"id": 12, "label": "invalid", "condition": "blur",
     "instruction": "Move the sheet up and down continuously while you press Capture."},
    {"id": 13, "label": "invalid", "condition": "blur",
     "instruction": "Rotate the sheet back and forth continuously while you press Capture."},
    {"id": 14, "label": "invalid", "condition": "blur",
     "instruction": "Shake the sheet more gently while you press Capture to create mild blur."},
    {"id": 15, "label": "invalid", "condition": "occlusion",
     "instruction": "Cover the left quarter of the sheet with your hand."},
    {"id": 16, "label": "invalid", "condition": "occlusion",
     "instruction": "Cover the right quarter of the sheet with your hand."},
    {"id": 17, "label": "invalid", "condition": "occlusion",
     "instruction": "Cover the center of the trace with your hand or sleeve."},
    {"id": 18, "label": "invalid", "condition": "occlusion",
     "instruction": "Place the pen or another object across a large part of the trace."},
    {"id": 19, "label": "invalid", "condition": "framing",
     "instruction": "Move the sheet left until part of the target is outside the frame."},
    {"id": 20, "label": "invalid", "condition": "framing",
     "instruction": "Move the sheet right until part of the target is outside the frame."},
    {"id": 21, "label": "invalid", "condition": "framing",
     "instruction": "Move the sheet upward until part of the target is outside the frame."},
    {"id": 22, "label": "invalid", "condition": "framing",
     "instruction": "Rotate the sheet enough that a corner and part of the target leave the frame."},
    {"id": 23, "label": "invalid", "condition": "lighting",
     "instruction": "Make the scene substantially darker than normal, then capture."},
    {"id": 24, "label": "invalid", "condition": "lighting",
     "instruction": "Cast a strong shadow across the center of the sheet."},
    {"id": 25, "label": "invalid", "condition": "lighting",
     "instruction": "Aim a bright light at the left side to create glare or overexposure."},
    {"id": 26, "label": "invalid", "condition": "lighting",
     "instruction": "Aim a bright light at the right side to create glare or overexposure."},
    {"id": 27, "label": "invalid", "condition": "wrong_scene",
     "instruction": "Show a blank sheet with no reference path or trace."},
    {"id": 28, "label": "invalid", "condition": "wrong_scene",
     "instruction": "Remove the sheet so only the work surface is visible."},
    {"id": 29, "label": "invalid", "condition": "wrong_scene",
     "instruction": "Place a different page or unrelated object under the camera."},
    {"id": 30, "label": "invalid", "condition": "wrong_scene",
     "instruction": "Cover most of the camera view so the tracing target cannot be identified."},
]


def dataset_filename(shot):
    condition = shot["condition"].replace("_", "-")
    return f'{shot["id"]:03d}_{shot["label"]}_{condition}.bmp'


def dataset_status():
    plan = []
    captured_count = 0
    for shot in IMAGE_QUALITY_PLAN:
        item = dict(shot)
        item["filename"] = dataset_filename(shot)
        path = os.path.join(IMAGE_QUALITY_CAPTURES, item["filename"])
        item["captured"] = os.path.isfile(path)
        if item["captured"]:
            captured_count += 1
            item["captured_at"] = datetime.fromtimestamp(
                os.path.getmtime(path), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            item["captured_at"] = None
        plan.append(item)
    next_shot = next((item["id"] for item in plan if not item["captured"]), None)
    return {"ok": True, "captured": captured_count, "total": len(plan),
            "next_shot": next_shot, "plan": plan}


def write_dataset_metadata():
    status = dataset_status()
    os.makedirs(IMAGE_QUALITY_DATA, exist_ok=True)
    manifest_path = os.path.join(IMAGE_QUALITY_DATA, "manifest.json")
    tmp_manifest = manifest_path + ".tmp"
    with open(tmp_manifest, "w") as f:
        json.dump({"schema_version": "1.0", "task": "image_quality_binary",
                   "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   "captured": status["captured"], "total": status["total"],
                   "shots": status["plan"]}, f, indent=2)
    os.replace(tmp_manifest, manifest_path)

    labels_path = os.path.join(IMAGE_QUALITY_DATA, "labels.csv")
    tmp_labels = labels_path + ".tmp"
    with open(tmp_labels, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "label", "condition", "shot_id", "captured_at"])
        for item in status["plan"]:
            if item["captured"]:
                writer.writerow(["captures/" + item["filename"], item["label"],
                                 item["condition"], item["id"], item["captured_at"]])
    os.replace(tmp_labels, labels_path)
    return status


def sdir():
    return os.path.join(SESSIONS, S["session_id"]) if S["session_id"] else None


def run(cmd, timeout=30):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, {"ok": False, "error": "timeout"}
    line = (p.stdout.strip().splitlines() or [""])[-1]
    try:
        return p.returncode, json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return p.returncode, {"ok": p.returncode == 0,
                              "raw": (p.stdout + p.stderr)[-400:]}


def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path))
    except (json.JSONDecodeError, OSError):
        return None


# ------------------------------------------------------------------ scoring
def _seg_dist(p, a, b):
    """Distance from point p to segment a-b (all [x,y])."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    l2 = abx * abx + aby * aby
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0]-a[0])*abx + (p[1]-a[1])*aby)/l2))
    cx, cy = a[0] + t*abx, a[1] + t*aby
    return math.hypot(p[0]-cx, p[1]-cy)


def poly_dist(p, poly):
    """Nearest (perpendicular) distance from point p to a polyline."""
    if len(poly) < 2:
        return 0.0
    return min(_seg_dist(p, poly[i], poly[i+1]) for i in range(len(poly)-1))


def perp_deviations(red, ref, x_tol=None):
    """True curve-to-curve deviations: each attempt point's nearest distance to
    the reference polyline. Orientation-independent, so steep sections aren't
    over-counted the way the vertical-slice distance is.

    Overlap assumption: where the red trace covers the blue reference, blue can't
    be detected there. If no reference point exists within `x_tol` of a red
    point's x, we assume the pen overlapped the reference (deviation 0) rather
    than measuring against a distant detected blue point."""
    if not red or len(ref) < 2:
        return []
    ref_xs = [p[0] for p in ref]
    devs = []
    for rp in red:
        if x_tol is not None and not any(abs(rx - rp[0]) <= x_tol for rx in ref_xs):
            devs.append(0.0)          # blue occluded here -> assume overlap
        else:
            devs.append(poly_dist(rp, ref))
    return devs


def imu_stability(imu):
    """IMU stability METRICS (not the 0-100 score). tremor_rms is the residual
    jitter after the slow intended trajectory is removed (high-pass |gyro|), so
    deliberate smooth tracing is NOT penalised — only shakiness/tremor is. The
    0-100 stability score is derived from tremor_rms by praxis.score."""
    if not imu:
        return {"gyro_rms_deg_s": None, "peak_angular_velocity_deg_s": None,
                "tremor_rms_deg_s": None}
    omega = [math.sqrt(o["gx"] ** 2 + o["gy"] ** 2 + o["gz"] ** 2) for o in imu]
    gyro_rms = math.sqrt(sum(w * w for w in omega) / len(omega))
    peak = max(omega)

    # sample rate -> moving-average half-window that captures intended motion
    dur = (imu[-1]["t"] - imu[0]["t"]) / 1e9 if len(imu) > 1 else 0
    fs = len(imu) / dur if dur > 0 else 100.0
    half = max(1, int(fs * TREMOR_WIN_S / 2))
    resid2 = 0.0
    for i in range(len(omega)):
        lo = max(0, i - half)
        hi = min(len(omega), i + half + 1)
        trend = sum(omega[lo:hi]) / (hi - lo)   # slow intended trajectory
        resid2 += (omega[i] - trend) ** 2       # high-frequency tremor
    tremor_rms = math.sqrt(resid2 / len(omega))
    return {"gyro_rms_deg_s": round(gyro_rms, 2),
            "peak_angular_velocity_deg_s": round(peak, 2),
            "tremor_rms_deg_s": round(tremor_rms, 2)}


def read_imu(d):
    imu, invalid = [], 0
    path = os.path.join(d, "imu.jsonl")
    if os.path.exists(path):
        for line in open(path):
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("meta"):
                continue
            if o.get("valid"):
                imu.append(o)
            else:
                invalid += 1
    return imu, invalid


def compute_metrics(d, t_go_ns, t_stop_ns):
    v = load_json(os.path.join(d, "score.json"))     # vision: pixel deviations
    imu, imu_invalid = read_imu(d)

    warnings = []
    m = {}
    if v and v.get("ok"):
        ref = v.get("reference") or []
        red = v.get("red") or []
        scale = SCALE_PX_PER_MM          # fixed rig calibration, not per-run
        cov = v.get("coverage_pct")
        frame_h = (v.get("frame") or [0, 1])[1] or 1

        # perpendicular (nearest-point) deviation — the accuracy basis.
        # x_tol applies the overlap assumption for occluded (red-over-blue) spans.
        perp = perp_deviations(red, ref, x_tol=SLICE_PX * 1.5)
        if perp:
            mean_px = sum(perp) / len(perp)
            max_px = max(perp)
            rms_px = math.sqrt(sum(x * x for x in perp) / len(perp))
        else:
            mean_px = max_px = rms_px = None
            warnings.append("no_deviation_points")

        m["mean_dev_px"] = round(mean_px, 2) if mean_px is not None else None
        m["max_dev_px"] = round(max_px, 2) if max_px is not None else None
        m["rms_dev_px"] = round(rms_px, 2) if rms_px is not None else None
        m["coverage_pct"] = cov
        m["scale_px_per_mm"] = scale
        if scale and mean_px is not None:
            m["mean_dev_mm"] = round(mean_px / scale, 2)
            m["max_dev_mm"] = round(max_px / scale, 2)
            m["rms_dev_mm"] = round(rms_px / scale, 2)
        else:
            m["mean_dev_mm"] = m["max_dev_mm"] = m["rms_dev_mm"] = None
            if not scale:
                warnings.append("scale_calibration_unavailable")
        # keep the raw vertical-slice figure for reference/debugging
        m["slice_mean_dev_px"] = v.get("mean_dev_px")
        # canonical versioned accuracy score (spatial error + coverage, mm-based)
        m["accuracy_score"] = praxis_score.accuracy_score(m["mean_dev_mm"], cov)
    else:
        for k in ("mean_dev_px", "max_dev_px", "rms_dev_px", "coverage_pct",
                  "mean_dev_mm", "max_dev_mm", "rms_dev_mm", "scale_px_per_mm",
                  "slice_mean_dev_px"):
            m[k] = None
        m["accuracy_score"] = None
        warnings.append("vision_no_score" if v is not None else "vision_no_output")

    m["completion_time_seconds"] = round((t_stop_ns - t_go_ns) / 1e9, 1)

    m.update(imu_stability(imu))
    # canonical versioned stability score (from high-frequency tremor)
    m["stability_score"] = praxis_score.stability_score(m.get("tremor_rms_deg_s"))
    if not imu:
        warnings.append("no_imu_samples")

    dur = (imu[-1]["t"] - imu[0]["t"]) / 1e9 if len(imu) > 1 else 0
    quality = {
        "n_ref_slices": (v or {}).get("n_ref_slices"),
        "n_scored_slices": (v or {}).get("n_scored_slices"),
        "frame": (v or {}).get("frame"),
        "imu_samples_received": len(imu),
        "imu_samples_invalid": imu_invalid,
        "imu_rate_hz": round(len(imu) / dur, 1) if dur > 0 else None,
        "calibration_valid": bool(S["imu_cal"] and S["imu_cal"].get("ok")),
        "warnings": warnings,
    }
    return m, quality


def forward_to_backend(run):
    """POST the finished run to the webapp ingestion API. Best-effort:
    returns a small status dict, never raises — the run is always kept locally."""
    if not BACKEND_URL:
        return {"forwarded": False, "reason": "no_backend_url"}
    url = BACKEND_URL + BACKEND_RUNS_PATH
    data = json.dumps(run).encode()
    headers = {"Content-Type": "application/json"}
    if BACKEND_KEY:
        headers["X-Device-Key"] = BACKEND_KEY
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=6) as resp:
            return {"forwarded": True, "status": resp.status, "url": url}
    except Exception as e:  # network down, backend off, etc. — keep local copy
        return {"forwarded": False, "reason": str(e), "url": url}


# ---------------------------------------------------------------- endpoints
def stop_camera_preview_locked():
    """Stop the persistent viewfinder. Caller must hold CAM_LOCK."""
    p = PROCS.pop("camera", None)
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=4)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=2)
    CAMERA["path"] = None


def start_camera_preview_locked(path):
    """Start one long-lived QNX viewfinder that atomically refreshes `path`."""
    p = PROCS.get("camera")
    if p and p.poll() is None and CAMERA["path"] == path:
        return True
    stop_camera_preview_locked()
    for stale in (path, path + ".tmp"):
        try:
            os.remove(stale)
        except OSError:
            pass
    p = subprocess.Popen([RT_VISION, "stream", "--out", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS["camera"] = p
    CAMERA["path"] = path
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if os.path.isfile(path):
            return True
        if p.poll() is not None:
            break
        time.sleep(0.05)
    stop_camera_preview_locked()
    return False


def api_new(body):
    with CAM_LOCK:
        stop_camera_preview_locked()
    sid = "session_" + datetime.now().strftime("%H%M%S")
    username = (body.get("username") or S.get("username") or "").strip()
    with LOCK:
        S.update(phase="idle", session_id=sid, imu_cal=None, score=None,
                 t_go=None, t_stop=None, result=None, error=None,
                 username=username)
    os.makedirs(os.path.join(SESSIONS, sid), exist_ok=True)
    return {"ok": True, "session_id": sid, "username": username}


def api_preview(_):
    if not S["session_id"]:
        api_new({})
    d = sdir()
    with CAM_LOCK:
        path = os.path.join(d, "preview.bmp")
        ok = start_camera_preview_locked(path)
    return {"ok": ok, "streaming": ok,
            "file": f"/sessions/{S['session_id']}/preview.bmp",
            "refresh_ms": 160,
            "error": None if ok else "camera_stream_unavailable"}


def api_dataset_preview(_):
    os.makedirs(IMAGE_QUALITY_DATA, exist_ok=True)
    path = os.path.join(IMAGE_QUALITY_DATA, "preview.bmp")
    with CAM_LOCK:
        stop_camera_preview_locked()
        code, out = run([RT_VISION, "preview", "--out", path], timeout=20)
    out["file"] = "/dataset-images/preview.bmp"
    return out


def api_dataset_capture(body):
    try:
        shot_id = int(body.get("shot_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_shot_id"}
    shot = next((item for item in IMAGE_QUALITY_PLAN if item["id"] == shot_id), None)
    if shot is None:
        return {"ok": False, "error": "unknown_shot_id"}

    os.makedirs(IMAGE_QUALITY_CAPTURES, exist_ok=True)
    filename = dataset_filename(shot)
    final_path = os.path.join(IMAGE_QUALITY_CAPTURES, filename)
    temp_path = final_path + ".tmp"
    with CAM_LOCK:
        stop_camera_preview_locked()
        code, out = run([RT_VISION, "capture", "--out", temp_path], timeout=25)
    if code != 0 or not out.get("ok") or not os.path.isfile(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass
        return {"ok": False, "error": out.get("error", "capture_failed"),
                "detail": out}

    os.replace(temp_path, final_path)
    status = write_dataset_metadata()
    return {"ok": True, "shot_id": shot_id, "filename": filename,
            "file": "/dataset-images/captures/" + filename,
            "captured": status["captured"], "total": status["total"],
            "next_shot": status["next_shot"]}


def api_go(body):
    """Start a run: calibrate IMU bias (hold still), then record IMU + timer."""
    if not S["session_id"]:
        api_new({})
    d = sdir()
    # short stationary bias calibration so the stability score is meaningful
    code, cal = run([IMU_PY, IMU_REC, "calibrate",
                     "--out", os.path.join(d, "imu_bias.json"),
                     "--seconds", "2"], timeout=20)
    with LOCK:
        S["imu_cal"] = cal
    if not cal.get("ok"):
        return {"ok": False, "error": "imu_calibration_failed", "detail": cal}

    stop = os.path.join(d, "STOP")
    if os.path.exists(stop):
        os.remove(stop)
    PROCS["imu"] = subprocess.Popen(
        [IMU_PY, IMU_REC, "record", "--bias", os.path.join(d, "imu_bias.json"),
         "--out", os.path.join(d, "imu.jsonl"), "--stopfile", stop],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with LOCK:
        S["t_go"] = time.monotonic_ns()
        S["phase"] = "recording"
    return {"ok": True, "imu_bias": cal.get("bias"), "noise_dps": cal.get("noise_dps")}


def api_stop(_):
    """Stop IMU recording + timer. Pen can now be lifted for the photo."""
    d = sdir()
    t_stop = time.monotonic_ns()
    open(os.path.join(d, "STOP"), "w").close()          # stops the IMU recorder
    p = PROCS.pop("imu", None)
    if p:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    with LOCK:
        S["t_stop"] = t_stop
        S["phase"] = "stopped"
    return {"ok": True, "duration_s": round((t_stop - (S["t_go"] or t_stop)) / 1e9, 1)}


def api_score(_):
    """After the pen is lifted: ONE photo -> vertical-slice blue-vs-red score,
    then persist the run and forward it to the webapp ingestion API."""
    d = sdir()
    t_stop = S["t_stop"] or time.monotonic_ns()
    with CAM_LOCK:
        stop_camera_preview_locked()
        # No per-run scale detection — px->mm is the fixed SCALE_PX_PER_MM.
        code, vis = run([RT_VISION, "score", "--out", os.path.join(d, "score.json"),
                         "--endbmp", os.path.join(d, "end.bmp"),
                         "--slice", str(SLICE_PX)], timeout=30)
    with LOCK:
        S["score"] = vis

    metrics, quality = compute_metrics(d, S["t_go"], t_stop)
    if not vis.get("ok"):
        quality["warnings"].append("capture_" + str(vis.get("error", "failed")))

    # The learned quality gate is isolated from acquisition and deterministic
    # scoring. Failure or timeout adds a warning but never removes raw results.
    end_image = os.path.join(d, "end.bmp")
    if os.path.isfile(end_image) and os.path.isfile(IMAGE_QUALITY_MODEL):
        iq_code, image_quality = run(
            [IMU_PY, IMAGE_QUALITY_INFER, "--model", IMAGE_QUALITY_MODEL,
             "--image", end_image], timeout=12)
    else:
        image_quality = {"ok": False, "error": "model_or_image_unavailable"}
    quality["image_quality"] = image_quality
    if not image_quality.get("ok"):
        quality["warnings"].append("ai_image_quality_unavailable")
    elif image_quality.get("classification") != "valid":
        quality["warnings"].append("ai_image_quality_repeat_recommended")

    # --- deterministic scoring -> banding -> stratification (in this order) ---
    acc = metrics.get("accuracy_score")
    stab = metrics.get("stability_score")
    bands = {"accuracy": praxis_score.band(acc),
             "stability": praxis_score.band(stab)}
    percentiles = praxis_pct.compute_percentiles(acc, stab, TASK)

    # --- explainability LAST, over a validated structured object ---
    explainer_input = praxis_explain.build_input(
        TASK, {"accuracy": acc, "stability": stab}, bands, percentiles,
        metrics, quality.get("warnings"), image_quality)
    explanation = praxis_explain.explain(explainer_input)

    v = load_json(os.path.join(d, "score.json")) or {}
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session = {
        "schema_version": "3.0",
        "username": S["username"] or "anonymous",
        "session_id": S["session_id"],
        "device_id": DEVICE_ID,
        "task": TASK,
        "created_at": now_iso,
        "timing": {
            "started_at": now_iso,
            "duration_ms": int((t_stop - S["t_go"]) / 1e6) if S["t_go"] else None,
        },
        "scores": {"accuracy": acc, "stability": stab,
                   "accuracy_band": bands["accuracy"],
                   "stability_band": bands["stability"],
                   "version": praxis_score.SCORE_VERSION},
        "score_definitions": praxis_score.score_definitions(),
        "percentiles": percentiles,
        "explanation": explanation,
        "metrics": metrics,
        "quality": quality,
        # detected polylines (image pixels) so the webapp can redraw the overlay
        "trace": {"frame": v.get("frame"),
                  "reference": v.get("reference", []),
                  "red": v.get("red", [])},
        # pointers to the raw artifacts saved alongside for the web app bundle
        "artifacts": {"imu_jsonl": "imu.jsonl", "imu_bias": "imu_bias.json",
                      "vision_score": "score.json", "end_image": "end.bmp",
                      "preview_image": "preview.bmp"},
    }
    with open(os.path.join(d, "session.json"), "w") as f:
        json.dump(session, f, indent=2)
    os.makedirs(OUTBOX, exist_ok=True)
    shutil.copy(os.path.join(d, "session.json"), os.path.join(OUTBOX, "latest.json"))
    session["_forward"] = forward_to_backend(session)
    with LOCK:
        S["result"] = session
        S["phase"] = "complete"
    return {"ok": True, "session": session}


ROUTES = {
    "/api/session/new": api_new,
    "/api/preview": api_preview,
    "/api/go": api_go,
    "/api/stop": api_stop,
    "/api/score": api_score,
    "/api/dataset/preview": api_dataset_preview,
    "/api/dataset/capture": api_dataset_capture,
}


def tail_imu_live(d):
    """Latest gyro magnitude + valid-sample count, for the live stability read."""
    path = os.path.join(d, "imu.jsonl")
    if not d or not os.path.exists(path):
        return {"n": 0, "gyro_mag": None}
    n, last = 0, None
    with open(path) as f:
        for line in f:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("valid"):
                n += 1
                last = o
    mag = (math.sqrt(last["gx"] ** 2 + last["gy"] ** 2 + last["gz"] ** 2)
           if last else None)
    return {"n": n, "gyro_mag": round(mag, 1) if mag is not None else None}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._file(os.path.join(DASH, "index.html"), "text/html")
        if path in ("/dataset", "/dataset.html"):
            return self._file(os.path.join(DASH, "dataset.html"), "text/html")
        if path == "/api/dataset/status":
            return self._json(dataset_status())
        if path == "/api/state":
            with LOCK:
                st = {k: S[k] for k in ("phase", "session_id", "username",
                                        "t_go", "t_stop", "result", "error")}
            v = load_json(os.path.join(sdir(), "score.json")) if sdir() else None
            if v:
                st["reference"] = v.get("reference", [])
                st["red"] = v.get("red", [])
                st["frame"] = v.get("frame")
            return self._json(st)
        if path == "/api/imu_live":
            return self._json(tail_imu_live(sdir() or ""))
        if path.startswith("/sessions/"):
            fp = os.path.join(BASE, path.lstrip("/"))
            ctype = "image/bmp" if fp.endswith(".bmp") else "application/json"
            return self._file(fp, ctype)
        if path.startswith("/dataset-images/"):
            relative = path[len("/dataset-images/"):]
            if relative not in ("preview.bmp",) and not any(
                    relative == "captures/" + dataset_filename(shot)
                    for shot in IMAGE_QUALITY_PLAN):
                return self.send_error(404)
            fp = os.path.join(IMAGE_QUALITY_DATA, relative)
            return self._file(fp, "image/bmp")
        if path == "/outbox/latest.json":
            return self._file(os.path.join(OUTBOX, "latest.json"), "application/json")
        self.send_error(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = {}
        if n:
            try:
                body = json.loads(self.rfile.read(n))
            except json.JSONDecodeError:
                pass
        fn = ROUTES.get(self.path)
        if not fn:
            return self.send_error(404)
        try:
            return self._json(fn(body))
        except Exception as e:
            with LOCK:
                S["error"] = str(e)
            return self._json({"ok": False, "error": str(e)}, 500)


def shutdown(_signum=None, _frame=None):
    with CAM_LOCK:
        stop_camera_preview_locked()
    raise SystemExit(0)


if __name__ == "__main__":
    os.makedirs(SESSIONS, exist_ok=True)
    os.makedirs(OUTBOX, exist_ok=True)
    os.makedirs(IMAGE_QUALITY_CAPTURES, exist_ok=True)
    write_dataset_metadata()
    with open(os.path.join(BASE, "server.pid"), "w") as f:
        f.write(str(os.getpid()))
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"Praxis server on :{PORT} (base {BASE})", flush=True)
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    finally:
        with CAM_LOCK:
            stop_camera_preview_locked()
