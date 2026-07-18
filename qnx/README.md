# RehabTrace — QNX side (HT6)

Upper-limb rehab prototype on Raspberry Pi 5 / QNX 8. A fixed overhead camera
watches a printed mat (4 red corner crosses + a **black reference line**); the
participant traces the line with a **red-ink pen** carrying an MPU6050 IMU.
Because the hand/pen occludes the tip mid-stroke, the camera is used **twice**
— once on the clean mat (capture the black reference) and once **after** the
task (photograph the red attempt) — while the IMU streams live throughout.
Camera → accuracy (red vs black), IMU → stability. All local; results are JSON
on the Pi's own web server.

**Dashboard:** `http://qnxpi23.local:8080/` — guided flow:
1. **Calibrate camera** (clean mat, black line only) → finds crosses, builds
   pixel→mm homography, captures the black line as the digital reference
2. **Calibrate IMU** (pencil still) → gyro bias
3. **GO** → IMU records live (timer + stability gauge) while the participant
   traces in red; **STOP** → one photo → red attempt extracted → scored vs the
   black reference. Overlay of both lines, end-state photo, `session.json` +
   `outbox/latest.json`

## Components

| Path | Runs | Role |
|---|---|---|
| `vision/rt_vision.cpp` | Pi (C++, `libcamapi`) | ONLY code touching the camera. `calibrate` + `track` modes, NV12 color math, homography, BMP snapshots |
| `imu/imu_recorder.py` | Pi (venv python) | MPU6050 bias calibration + session recording (JSONL) |
| `server/server.py` | Pi (python stdlib) | Control API + static dashboard + metric computation |
| `dashboard/index.html` | browser | The UI (any device on the hotspot) |

Per-session artifacts in `~/steadyeye/sessions/<id>/`: `snapshot.bmp` (clean mat),
`calib.json`, `reference.json` (original trace, mm polyline), `trace.jsonl`
(drawn trace), `imu.jsonl`, `end.bmp` (end state), `session.json` (metrics).

## Dev loop

```bash
cd qnx
make deploy   # sync + compile rt_vision on the Pi + restart server
make dash     # open the dashboard
```

## Requirements on the Pi

- Headers (one-time): `sudo apk add qnx-sensor-framework-dev qnx-screen-dev`
- Camera at `/dev/sensor/camera1`, MPU6050 at `0x68` on `/dev/i2c1` (verified)
- Mat: red crosses ~15 mm from each edge of letter paper (centres at
  (15,15)…(200.9,264.4) mm — pass `--corners` to rt_vision if different),
  thick black non-self-crossing reference line, decent even lighting
- Pen: draws **RED ink** (the attempt). Corner cross regions are masked when
  extracting the red attempt, so red crosses + red attempt coexist — just keep
  the traced line from running through the corner crosses.

## Notes / limitations

- Prototype task-performance measures — not validated clinical metrics.
- IMU sampling is best-effort (~100–200 Hz Python); real timestamps recorded,
  no fabricated samples; invalid reads counted, never interpolated.
- Lost camera tracking → frame marked invalid and counted, never reused.
