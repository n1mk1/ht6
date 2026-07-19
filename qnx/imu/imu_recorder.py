#!/usr/bin/env python3
"""MPU6050 recorder for Praxis.

Modes:
  calibrate --out bias.json [--seconds 2]
      Device must be STATIONARY. Estimates gyro bias (mean) and noise (std).
      ok=false if the pen was moving (std too high).
  record --bias bias.json --out imu.jsonl --stopfile STOP
      Samples as fast as the bus allows (~100-200 Hz), monotonic timestamps,
      bias-corrected gyro. One JSON object per line. First line is metadata.
      Stops when the stopfile appears.

Run with the venv python: /data/home/qnxuser/venv/bin/python
"""
import argparse
import json
import math
import os
import sys
import time

import mpu6050

ADDR = 0x68


def now_ns():
    return time.monotonic_ns()


def calibrate(args):
    m = mpu6050.mpu6050(ADDR)
    t_end = time.monotonic() + args.seconds
    gx, gy, gz, n = [], [], [], 0
    while time.monotonic() < t_end:
        g = m.get_gyro_data()
        gx.append(g["x"]); gy.append(g["y"]); gz.append(g["z"])
        n += 1

    def mean(v): return sum(v) / len(v)
    def std(v):
        mu = mean(v)
        return math.sqrt(sum((x - mu) ** 2 for x in v) / len(v))

    bias = {"x": mean(gx), "y": mean(gy), "z": mean(gz)}
    noise = max(std(gx), std(gy), std(gz))
    ok = n >= 50 and noise < 3.0  # deg/s: moving pen fails this
    out = {"ok": ok, "bias": bias, "noise_dps": round(noise, 3),
           "samples": n, "seconds": args.seconds}
    with open(args.out, "w") as f:
        json.dump(out, f)
    print(json.dumps(out), flush=True)
    return 0 if ok else 3


def record(args):
    bias = {"x": 0.0, "y": 0.0, "z": 0.0}
    if args.bias and os.path.exists(args.bias):
        with open(args.bias) as f:
            bias = json.load(f)["bias"]
    m = mpu6050.mpu6050(ADDR)
    n = 0
    t0 = now_ns()
    with open(args.out, "w") as f:
        f.write(json.dumps({"meta": True, "t0": t0, "bias": bias}) + "\n")
        buf = []
        while not os.path.exists(args.stopfile):
            try:
                a = m.get_accel_data()  # m/s^2
                g = m.get_gyro_data()   # deg/s
                t = now_ns()
            except OSError:
                buf.append(json.dumps({"t": now_ns(), "valid": False}))
                continue
            buf.append(json.dumps({
                "t": t, "valid": True,
                "gx": round(g["x"] - bias["x"], 3),
                "gy": round(g["y"] - bias["y"], 3),
                "gz": round(g["z"] - bias["z"], 3),
                "ax": round(a["x"], 3), "ay": round(a["y"], 3),
                "az": round(a["z"], 3),
            }))
            n += 1
            if len(buf) >= 50:
                f.write("\n".join(buf) + "\n")
                f.flush()
                buf.clear()
        if buf:
            f.write("\n".join(buf) + "\n")
    dur = (now_ns() - t0) / 1e9
    rate = n / dur if dur > 0 else 0
    print(json.dumps({"samples": n, "seconds": round(dur, 2),
                      "rate_hz": round(rate, 1)}), flush=True)
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("--out", required=True)
    c.add_argument("--seconds", type=float, default=2.0)
    r = sub.add_parser("record")
    r.add_argument("--bias", default="")
    r.add_argument("--out", required=True)
    r.add_argument("--stopfile", required=True)
    args = p.parse_args()
    sys.exit(calibrate(args) if args.mode == "calibrate" else record(args))


if __name__ == "__main__":
    main()
