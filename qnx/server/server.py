#!/usr/bin/env python3
"""RehabTrace control server — runs ON the QNX Pi. Stdlib only.

Flow (post-hoc image model): calibrate camera on the CLEAN mat (black line +
red crosses) -> capture black reference. Calibrate IMU. GO records IMU live
(stability + timer) while the participant traces in RED ink. STOP takes ONE
photo, extracts the red attempt line, and scores it against the black
reference.

  GET  /                       dashboard
  GET  /api/state              phase + reference (black) + attempt (red)
  GET  /api/imu_live           latest gyro magnitude + sample count (during run)
  POST /api/session/new        {"participant": "..."}
  POST /api/calibrate/camera   rt_vision calibrate  (CLEAN mat, no red yet)
  POST /api/calibrate/imu      stationary gyro bias
  POST /api/go                 start IMU recording + timer
  POST /api/stop               stop IMU, take photo, extract red, score
"""
import json
import math
import os
import shutil
import subprocess
import threading
import time
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

CORRIDOR_MM = 5.0   # attempt point in-bounds if <= this from reference
COVERAGE_MM = 6.0   # a reference point is "covered" if an attempt point is this close

S = {
    "phase": "idle",   # idle -> cam_ok -> imu_ok -> recording -> ended -> complete
    "session_id": None, "participant": "demo_01",
    "camera": None, "imu_cal": None,
    "t_go": None, "t_stop": None, "result": None, "error": None,
}
LOCK = threading.Lock()
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


def load_points(path):
    if not os.path.exists(path):
        return []
    try:
        return json.load(open(path)).get("points_mm", [])
    except (json.JSONDecodeError, OSError):
        return []


# ------------------------------------------------------------------ metrics
def seg_dist(px, py, ax, ay, bx, by):
    abx, aby = bx - ax, by - ay
    l2 = abx * abx + aby * aby
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / l2))
    cx, cy = ax + t * abx, ay + t * aby
    return math.hypot(px - cx, py - cy)


def poly_dist(p, ref):
    if len(ref) < 2:
        return 0.0
    return min(seg_dist(p[0], p[1], ref[i][0], ref[i][1], ref[i + 1][0], ref[i + 1][1])
               for i in range(len(ref) - 1))


def compute_metrics(d, t_go_ns, t_stop_ns):
    ref = load_points(os.path.join(d, "reference.json"))   # black, from calibrate
    att = load_points(os.path.join(d, "attempt.json"))     # red, from capture

    imu, imu_invalid = [], 0
    imu_path = os.path.join(d, "imu.jsonl")
    if os.path.exists(imu_path):
        for line in open(imu_path):
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("meta"):
                continue
            imu.append(o) if o.get("valid") else (imu_invalid := imu_invalid + 1)

    m, warnings = {}, []
    # accuracy: red attempt vs black reference
    if att and len(ref) >= 2:
        devs = [poly_dist(p, ref) for p in att]
        m["mean_path_deviation_mm"] = round(sum(devs) / len(devs), 2)
        m["maximum_path_deviation_mm"] = round(max(devs), 2)
        m["path_within_bounds_pct"] = round(
            100.0 * sum(1 for v in devs if v <= CORRIDOR_MM) / len(devs), 1)
        covered = sum(1 for r in ref
                      if any(math.hypot(p[0] - r[0], p[1] - r[1]) <= COVERAGE_MM
                             for p in att))
        m["path_coverage_pct"] = round(100.0 * covered / len(ref), 1)
    else:
        for k in ("mean_path_deviation_mm", "maximum_path_deviation_mm",
                  "path_within_bounds_pct", "path_coverage_pct"):
            m[k] = None
        warnings.append("no_attempt_line" if not att else "no_reference_line")
    m["completion_time_seconds"] = round((t_stop_ns - t_go_ns) / 1e9, 1)

    # stability: IMU during the run
    if imu:
        mags2 = [o["gx"] ** 2 + o["gy"] ** 2 + o["gz"] ** 2 for o in imu]
        m["gyro_rms_deg_s"] = round(math.sqrt(sum(mags2) / len(mags2)), 2)
        m["peak_angular_velocity_deg_s"] = round(math.sqrt(max(mags2)), 2)
        dur = (imu[-1]["t"] - imu[0]["t"]) / 1e9 if len(imu) > 1 else 0
        m["_imu_rate_hz"] = round(len(imu) / dur, 1) if dur > 0 else None
    else:
        m["gyro_rms_deg_s"] = None
        m["peak_angular_velocity_deg_s"] = None
        warnings.append("no_imu_samples")

    quality = {
        "attempt_points": len(att),
        "reference_points": len(ref),
        "imu_samples_received": len(imu),
        "imu_samples_invalid": imu_invalid,
        "imu_rate_hz": m.pop("_imu_rate_hz", None),
        "calibration_valid": bool(S["imu_cal"] and S["imu_cal"].get("ok")),
        "warnings": warnings,
    }
    return m, quality


def compute_scores(m):
    """Two 0-100 prototype summary scores (NOT clinical).
    accuracy = how well the red attempt followed the black reference;
    stability = how steady the pen was (from gyro RMS)."""
    wb = m.get("path_within_bounds_pct")
    cov = m.get("path_coverage_pct")
    accuracy = round(0.6 * wb + 0.4 * cov, 1) if (wb is not None and cov is not None) else None
    rms = m.get("gyro_rms_deg_s")
    # 100 at 0 deg/s, ~78 @ 5, ~61 @ 10, ~22 @ 30 — smooth, monotonic.
    stability = round(100.0 * math.exp(-rms / 20.0), 1) if rms is not None else None
    return {"accuracy": accuracy, "stability": stability}


# ---------------------------------------------------------------- endpoints
def api_new(body):
    sid = "session_" + datetime.now().strftime("%H%M%S")
    with LOCK:
        S.update(phase="idle", session_id=sid, camera=None, imu_cal=None,
                 t_go=None, result=None, error=None,
                 participant=body.get("participant", "demo_01"))
    os.makedirs(os.path.join(SESSIONS, sid), exist_ok=True)
    return {"ok": True, "session_id": sid}


def api_preview(_):
    if not S["session_id"]:
        api_new({})
    d = sdir()
    code, out = run([RT_VISION, "preview", "--out", os.path.join(d, "preview.bmp")],
                    timeout=20)
    out["file"] = f"/sessions/{S['session_id']}/preview.bmp"
    return out


def api_cal_camera(body):
    if not S["session_id"]:
        api_new({})
    cmd = [RT_VISION, "calibrate", "--out", sdir()]
    # Manual corners from UI clicks: [[x,y]*4] in image pixels, TL,TR,BR,BL.
    corners = body.get("corners_px")
    if corners and len(corners) == 4:
        flat = ",".join(f"{p[0]:.1f},{p[1]:.1f}" for p in corners)
        cmd += ["--corners-px", flat]
    code, out = run(cmd, timeout=30)
    with LOCK:
        S["camera"] = out
        if out.get("ok"):
            S["phase"] = "cam_ok"
    return out


def api_cal_imu(_):
    d = sdir()
    code, out = run([IMU_PY, IMU_REC, "calibrate",
                     "--out", os.path.join(d, "imu_bias.json"),
                     "--seconds", "2"], timeout=20)
    with LOCK:
        S["imu_cal"] = out
        if out.get("ok") and S["phase"] == "cam_ok":
            S["phase"] = "imu_ok"
    return out


def api_go(_):
    d = sdir()
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
    return {"ok": True}


def api_end(_):
    """End the run: stop IMU recording only. Pen can now be cleared."""
    d = sdir()
    t_stop = time.monotonic_ns()
    open(os.path.join(d, "STOP"), "w").close()
    p = PROCS.pop("imu", None)
    if p:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    with LOCK:
        S["t_stop"] = t_stop
        S["phase"] = "ended"
    return {"ok": True, "duration_s": round((t_stop - S["t_go"]) / 1e9, 1)}


def api_score(_):
    """After the pen is removed: photograph, extract red attempt, score."""
    d = sdir()
    t_stop = S["t_stop"] or time.monotonic_ns()

    # ONE post-task photo -> red attempt line.
    code, cap = run([RT_VISION, "capture", "--calib", d,
                     "--out", os.path.join(d, "attempt.json"),
                     "--endbmp", os.path.join(d, "end.bmp")], timeout=30)

    metrics, quality = compute_metrics(d, S["t_go"], t_stop)
    if not cap.get("ok"):
        quality["warnings"].append("capture_" + str(cap.get("error", "failed")))

    session = {
        "schema_version": "1.0",
        "session_id": S["session_id"],
        "participant_id": S["participant"],
        "device_id": "qnx_pi_23",
        "task": {"type": "path_tracing", "version": "mat_v1"},
        "timing": {
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_ms": int((t_stop - S["t_go"]) / 1e6),
        },
        "scores": compute_scores(metrics),
        "metrics": metrics,
        "quality": quality,
    }
    with open(os.path.join(d, "session.json"), "w") as f:
        json.dump(session, f, indent=2)
    os.makedirs(OUTBOX, exist_ok=True)
    shutil.copy(os.path.join(d, "session.json"), os.path.join(OUTBOX, "latest.json"))
    with LOCK:
        S["result"] = session
        S["phase"] = "complete"
    return {"ok": True, "session": session}


ROUTES = {
    "/api/session/new": api_new,
    "/api/calibrate/camera": api_cal_camera,
    "/api/calibrate/imu": api_cal_imu,
    "/api/go": api_go,
    "/api/stop": api_stop,
}


def tail_imu_live(d):
    """Latest gyro magnitude + count, for the live 'stability' readout."""
    path = os.path.join(d, "imu.jsonl")
    if not os.path.exists(path):
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
                st = dict(S)
            d = sdir()
            if d:
                st["reference"] = load_points(os.path.join(d, "reference.json"))
                st["attempt"] = load_points(os.path.join(d, "attempt.json"))
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
