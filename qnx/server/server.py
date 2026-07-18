#!/usr/bin/env python3
"""RehabTrace control server — runs ON the QNX Pi. Stdlib only.

Single-image model (no corner markers, no homography):

  live camera view -> START (calibrate IMU bias, then record IMU + timer)
  -> participant traces the printed BLUE pattern in RED ink -> STOP (stop IMU
  + timer) -> lift the pen -> CAPTURE & SCORE (one photo containing both the
  blue reference and the red trace; accuracy = per-vertical-slice pixel distance
  between the blue and red centroids; stability = IMU tremor during the run).
  Each run is tagged with the participant's username, saved locally, and (if
  BACKEND_URL is set) POSTed to the webapp backend for MongoDB storage.

  GET  /                     dashboard
  GET  /api/state            phase + captured black/red polylines (pixels)
  GET  /api/imu_live         latest gyro magnitude + sample count (during run)
  POST /api/session/new      {"username": "..."}
  POST /api/preview          grab one frame -> preview.bmp (live view)
  POST /api/go               calibrate IMU bias, then start IMU recording + timer
  POST /api/stop             stop IMU recording + timer
  POST /api/score            one photo -> vertical-slice black-vs-red scoring
"""
import json
import math
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.expanduser("~/steadyeye")
DASH = os.path.join(BASE, "dashboard")
SESSIONS = os.path.join(BASE, "sessions")
OUTBOX = os.path.join(BASE, "outbox")
RT_VISION = os.path.join(BASE, "vision", "rt_vision")
IMU_PY = os.path.expanduser("~/venv/bin/python")
IMU_REC = os.path.join(BASE, "imu", "imu_recorder.py")
PORT = 8080

# Webapp backend (on a separate computer) that ingests runs into MongoDB.
# Set BACKEND_URL to its base URL, e.g. http://192.168.1.50:8000 — the server
# POSTs each finished run to BACKEND_URL + BACKEND_RUNS_PATH. If unset or
# unreachable, the run is still saved locally to outbox/latest.json.
BACKEND_URL = os.environ.get("BACKEND_URL", "").rstrip("/")
BACKEND_RUNS_PATH = os.environ.get("BACKEND_RUNS_PATH", "/api/runs")
BACKEND_KEY = os.environ.get("BACKEND_KEY", "")   # optional X-Device-Key
DEVICE_ID = os.environ.get("DEVICE_ID", "qnx_pi_23")

SLICE_PX = 16          # vertical-slice width for accuracy scoring
# Accuracy tolerance: mean per-slice deviation as a fraction of frame height.
# score = 100*exp(-(mean_dev_px/frame_h)/DEV_TOL_FRAC), then scaled by coverage.
# 3% of a 1296px frame ~= 39px at the "37/100" point. Tune after a real run.
DEV_TOL_FRAC = 0.03
# Stability = steadiness of the pen, isolating tremor from the deliberate
# tracing motion. We high-pass |gyro|: subtract a ~TREMOR_WIN_S moving average
# (the intended, slow trajectory) and take the RMS of the residual jitter.
# score = 100*exp(-tremor_rms/TREMOR_TOL). A still/smooth hand -> tremor near 0
# -> ~100; shakiness raises tremor_rms. Calibrate TREMOR_TOL with one smooth and
# one deliberately shaky trace: set it near the shaky run's tremor_rms (~37/100).
TREMOR_WIN_S = 0.3     # moving-average window (s) that defines "intended motion"
TREMOR_TOL = 6.0       # deg/s residual jitter at the ~37/100 point

S = {
    "phase": "idle",   # idle -> recording -> stopped -> complete
    "session_id": None, "username": "",
    "imu_cal": None, "score": None,
    "t_go": None, "t_stop": None, "result": None, "error": None,
}
LOCK = threading.Lock()
CAM_LOCK = threading.Lock()   # only one rt_vision may hold the camera at a time
PROCS = {}


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
def accuracy_from_vision(v):
    """0-100 accuracy from the vertical-slice pixel deviations.

    position score decays with mean per-slice |y_red - y_black| (normalised by
    frame height so it is roughly zoom-independent); then scaled by coverage so
    untraced parts of the pattern lower the score."""
    if not v or not v.get("ok"):
        return None
    frame_h = (v.get("frame") or [0, 1])[1] or 1
    mean_dev = v.get("mean_dev_px")
    cov = v.get("coverage_pct")
    if mean_dev is None or cov is None:
        return None
    norm = (mean_dev / frame_h) / DEV_TOL_FRAC
    position = 100.0 * math.exp(-norm)
    return round(position * (cov / 100.0), 1)


def imu_stability(imu):
    """Return (metrics, stability_score). Stability = residual jitter after the
    slow intended trajectory is removed (high-pass |gyro|), so deliberate smooth
    tracing is NOT penalised — only shakiness/tremor is. Raw gyro RMS and peak
    are reported too."""
    if not imu:
        return {"gyro_rms_deg_s": None, "peak_angular_velocity_deg_s": None,
                "tremor_rms_deg_s": None}, None
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
    stability = round(100.0 * math.exp(-tremor_rms / TREMOR_TOL), 1)
    return ({"gyro_rms_deg_s": round(gyro_rms, 2),
             "peak_angular_velocity_deg_s": round(peak, 2),
             "tremor_rms_deg_s": round(tremor_rms, 2)}, stability)


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
    m["accuracy_score"] = accuracy_from_vision(v)
    if v and v.get("ok"):
        m["mean_dev_px"] = v.get("mean_dev_px")
        m["max_dev_px"] = v.get("max_dev_px")
        m["rms_dev_px"] = v.get("rms_dev_px")
        m["coverage_pct"] = v.get("coverage_pct")
    else:
        for k in ("mean_dev_px", "max_dev_px", "rms_dev_px", "coverage_pct"):
            m[k] = None
        warnings.append("vision_no_score" if v is not None else "vision_no_output")

    m["completion_time_seconds"] = round((t_stop_ns - t_go_ns) / 1e9, 1)

    imu_m, stability = imu_stability(imu)
    m.update(imu_m)
    m["stability_score"] = stability
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
    """POST the finished run to the webapp backend (MongoDB ingest). Best-effort:
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
def api_new(body):
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
        code, out = run([RT_VISION, "preview", "--out", os.path.join(d, "preview.bmp")],
                        timeout=20)
    out["file"] = f"/sessions/{S['session_id']}/preview.bmp"
    return out


def api_go(_):
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
    then persist the run and forward it to the webapp backend (MongoDB)."""
    d = sdir()
    t_stop = S["t_stop"] or time.monotonic_ns()
    with CAM_LOCK:
        code, vis = run([RT_VISION, "score", "--out", os.path.join(d, "score.json"),
                         "--endbmp", os.path.join(d, "end.bmp"),
                         "--slice", str(SLICE_PX)], timeout=30)
    with LOCK:
        S["score"] = vis

    metrics, quality = compute_metrics(d, S["t_go"], t_stop)
    if not vis.get("ok"):
        quality["warnings"].append("capture_" + str(vis.get("error", "failed")))

    v = load_json(os.path.join(d, "score.json")) or {}
    session = {
        "schema_version": "2.1",
        "username": S["username"] or "anonymous",
        "session_id": S["session_id"],
        "device_id": DEVICE_ID,
        "task": {"type": "path_tracing", "version": "slice_v1"},
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timing": {
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_ms": int((t_stop - S["t_go"]) / 1e6) if S["t_go"] else None,
        },
        "scores": {"accuracy": metrics.get("accuracy_score"),
                   "stability": metrics.get("stability_score")},
        "metrics": metrics,
        "quality": quality,
        # detected polylines (image pixels) so the webapp can redraw the overlay
        "trace": {"frame": v.get("frame"),
                  "reference": v.get("reference", []),
                  "red": v.get("red", [])},
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


if __name__ == "__main__":
    os.makedirs(SESSIONS, exist_ok=True)
    os.makedirs(OUTBOX, exist_ok=True)
    with open(os.path.join(BASE, "server.pid"), "w") as f:
        f.write(str(os.getpid()))
    print(f"RehabTrace server on :{PORT} (base {BASE})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
