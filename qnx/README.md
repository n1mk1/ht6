# Praxis QNX capture system

This directory contains the Raspberry Pi 5 / QNX 8 hardware workflow for the
Praxis path-tracing prototype. A fixed overhead camera captures the printed
**blue reference path** and the participant's **red attempt** in one post-task
image. An MPU6050 attached to the pen records movement during the task.

Camera data produces deterministic accuracy and coverage measurements. IMU data
produces deterministic stability and movement measurements. Each completed run
is stored locally as JSON and can be uploaded to the isolated Praxis web API.

> These are prototype task-performance measurements, not validated clinical
> metrics. They do not diagnose, screen for, or grade a medical condition.

## Operator flow

Open `http://qnxpi23.local:8080/` and complete these steps:

1. Enter the participant username and use the persistent live camera feed to
   position the complete mat inside the frame.
2. Select **Start**. Keep the pen still during the two-second IMU bias
   calibration, then trace the blue path in red.
3. Select **Stop** and lift the pen out of the camera view.
4. Select **Capture & Score**. The camera captures one settled frame containing
   both paths, computes deterministic scores, validates image usability with the
   trained model, runs the grounded QNX llama analysis, saves the bundle, and
   attempts the upload.

Use the same username on the web dashboard to connect the run to the correct
participant record. Matching on the backend is case-insensitive and ignores
surrounding spaces.

## Components

| Path | Runtime | Responsibility |
|---|---|---|
| `vision/rt_vision.cpp` | QNX Pi, C++/`libcamapi` | The only camera access; persistent `stream`, `preview`, `capture`, and `score` modes with NV12 colour segmentation |
| `imu/imu_recorder.py` | QNX Pi, Python | MPU6050 bias calibration and timestamped JSONL recording |
| `server/server.py` | QNX Pi, Python stdlib | Control API, scoring pipeline, local persistence, and best-effort web upload |
| `praxis/` | QNX Pi, Python | Versioned score mapping, percentiles, and validated explanation generation |
| `dashboard/index.html` | Browser | Device control interface |
| `image_quality/` | QNX Pi and development computer | Separate image-usability model and training scripts |

See [`AI_ARCHITECTURE.md`](AI_ARCHITECTURE.md) for the model design, captured
training data, QNX llama.cpp package and GGUF setup, latency optimization
process, failure isolation, measured results, and engineering tradeoffs.

The canonical task metadata is currently:

```json
{"type": "path_tracing", "version": "mat_v1", "difficulty": 1}
```

Change task metadata only when the actual template or relevant difficulty
changes. The web API compares runs only when task type, version, difficulty,
and hand metadata are compatible.

## Session output

Each run is saved under `~/steadyeye/sessions/<session_id>/`:

| File | Contents |
|---|---|
| `imu.jsonl` | Timestamped raw and bias-corrected IMU samples |
| `imu_bias.json` | Two-second stationary calibration result |
| `score.json` | Vision centroids and pixel-level scoring output |
| `end.bmp` | Post-task scoring image |
| `preview.bmp` | Latest preview frame |
| `session.json` | Complete schema `3.0` run bundle |

The complete payload is also copied to `~/steadyeye/outbox/latest.json` and
posted to `BACKEND_URL + BACKEND_RUNS_PATH`. Upload is best-effort: a network or
API failure never removes the local session. The current device code does not
automatically replay older outbox entries, so retrying a failed historical
upload remains an operational/manual step.

## Web API configuration

Launch the QNX server with:

```bash
BACKEND_URL=http://<backend-computer-lan-ip>:8000 \
BACKEND_RUNS_PATH=/api/v1/qnx/sessions \
BACKEND_KEY=<optional-shared-device-key> \
~/venv/bin/python server/server.py
```

Do not use `localhost` for a backend running on another computer. If
`BACKEND_KEY` is set, it must match `PRAXIS_DEVICE_KEY` on the backend. The
legacy default path `/api/runs` remains accepted by the current API.

The emitted schema `3.0` contains username, device/session identity, task and
version metadata, timing, scores and score definitions, metrics, quality,
trace points, percentiles, explanation metadata, and artifact pointers. See
[`METRICS.md`](METRICS.md) for exact formulas and output shapes.

## Development and deployment

Defaults are defined in `env.sh`: host `qnxpi23.local`, user `qnxuser`, SSH key
`$HOME/.ssh/qnxpi`, and remote directory
`/data/home/qnxuser/steadyeye`. Override those shell variables for another Pi.

```bash
cd qnx
make deploy
make dash
```

Useful targets include `make sync`, `make build`, `make server`, `make shell`,
`make imu-cal`, `make ai-train`, `make ai-install`, and `make ai-models`. Run
the deterministic scoring and image-quality tests from the repository root:

```bash
python3 qnx/tests/test_praxis.py
python3 qnx/tests/test_image_quality.py
```

## Hardware and setup

- QNX sensor framework and Screen development headers are required to compile
  `rt_vision`.
- The configured camera is `/dev/sensor/camera1`.
- The MPU6050 is expected at address `0x68` on `/dev/i2c1`.
- The printed task uses a blue reference path and a red-ink attempt.
- Camera height, paper position, lighting, instructions, pen, and task template
  should remain fixed for meaningful comparisons.
- Pixel-to-millimetre conversion uses the fixed `SCALE_PX_PER_MM` calibration
  in `server/server.py`. Recalibrate when the rig geometry changes; there is no
  per-run homography or corner-marker calibration.

## Image-quality dataset

The separate collection workflow at `http://qnxpi23.local:8080/dataset` guides
an operator through 30 labeled full-resolution captures. It does not change the
normal scoring path. See
[`datasets/image_quality/README.md`](datasets/image_quality/README.md) and use
`make pull-dataset` to copy captures from the Pi.

## Known limitations

- IMU collection is best-effort Python sampling; actual timestamps are stored,
  invalid reads are counted, and samples are not fabricated or interpolated.
- Colour thresholds and fixed px/mm calibration depend on a controlled rig.
- Stability uses a boxcar high-pass approximation rather than a validated
  tremor-frequency analysis.
- Percentiles are unavailable unless a compatible versioned reference stratum
  has enough real samples.
- QNX upload currently preserves only `outbox/latest.json` as the forwarding
  pointer and has no automatic replay worker.
