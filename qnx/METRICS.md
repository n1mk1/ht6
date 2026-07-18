# RehabTrace — how the metrics are computed

Reference for every number a run produces: what it means, the exact formula,
and where it lives in the code. Two families of metrics — **accuracy** (from one
post‑task photo) and **stability** (from the IMU stream during the trace) — plus
timing and quality fields.

- Vision (pixels): `qnx/vision/rt_vision.cpp`, `do_score`
- Scoring + IMU (0–100 scores): `qnx/server/server.py`
  (`accuracy_from_vision`, `imu_stability`, `compute_metrics`)

All scores are **prototype task‑performance measures, not validated clinical
metrics.**

---

## 0. Pipeline at a glance

```
live view → START (IMU bias cal, then record) → trace blue line in red
          → STOP (stop IMU + timer) → lift pen → CAPTURE & SCORE (one photo)
```

- The **camera** touches nothing until CAPTURE & SCORE, which grabs one settled
  frame containing BOTH the printed **blue** reference and the drawn **red**
  trace, and scores accuracy from it.
- The **IMU** records the whole time between START and STOP; stability is
  computed from that stream.

---

## 1. Colour detection (feeds accuracy)

Detection runs directly on the NV12 Y/UV planes (no OpenCV). Reference = blue,
attempt = red; they sit in opposite chroma corners so they never bleed.

| Colour | Rule (per pixel) | Default thresholds |
|---|---|---|
| **Red** (attempt) | `Cr ≥ red_v_min` and `Cb ≤ red_u_max` and `Y ≥ red_y_min` | 150 / 128 / 60 |
| **Blue** (reference) | `Cb ≥ blue_u_min` and `Cr ≤ blue_v_max` and `Y ≥ blue_y_min` | 150 / 120 / 30 |

Overridable on the `rt_vision score` CLI: `--red-v`, `--blue-u`, `--blue-v`.

---

## 2. Accuracy

Idea: for a **left→right** line (single‑valued in x), walk the image in vertical
slices; in each slice the blue reference and the red trace each reduce to one
centroid, and the per‑slice error is their vertical pixel distance.

### Stage 1 — per‑slice pixel error (`rt_vision.cpp`, `do_score`)

- Image is split into vertical slices `SLICE_PX = 16` px wide.
- A colour is "present" in a slice only if it has `≥ MIN_HITS = 3` subsampled
  pixels (pixels are sampled every 2 px in x and y for speed).
- For a present colour, the slice centroid is the mean (x, y) of its pixels.
- For a slice with **both** colours present:

  ```
  dev = | y_red_centroid − y_blue_centroid |     # pixels
  ```

Aggregated into `score.json`:

| Field | Meaning |
|---|---|
| `mean_dev_px` | mean of `dev` over scored slices |
| `max_dev_px` | max `dev` |
| `rms_dev_px` | RMS of `dev` |
| `n_ref_slices` | slices containing blue (the reference) |
| `n_scored_slices` | slices with **both** blue and red |
| `coverage_pct` | `100 × n_scored_slices / n_ref_slices` |
| `ref_extent_px` | vertical span (max−min y) of the blue centroids |
| `reference`, `red` | the two centroid polylines (image pixels, for overlay) |
| `frame` | `[width, height]` of the frame |

### How edge / mismatched slices are handled

| Slice content | Effect on score |
|---|---|
| **Blue + red** | scored — contributes to `mean_dev_px` |
| **Blue only** (part of line not traced) | **excluded** from deviation; lowers **coverage** (in `n_ref` but not `n_scored`) |
| **Red only** (overshoot past the line) | **ignored** for scoring (drawn in overlay only); not in `n_ref` or `n_scored` |

So under‑tracing is penalised via coverage; over‑tracing/overshoot is currently
**not** penalised. (Alternatives — penalise overshoot as `spill_pct`, or clamp
scoring to the reference's x‑range — are easy changes if wanted.)

### Stage 2 — map to 0–100 (`server.py`, `accuracy_from_vision`)

```python
norm     = (mean_dev_px / frame_h) / DEV_TOL_FRAC   # DEV_TOL_FRAC = 0.03
position = 100 * exp(-norm)                          # closeness where traced
accuracy = round(position * (coverage_pct / 100), 1)
```

Two factors multiply:

1. **Position (closeness).** `mean_dev_px` is normalised by frame **height** so
   the score is roughly independent of camera zoom/distance, then decayed
   exponentially. `DEV_TOL_FRAC = 0.03` sets the scale: a mean error of **3 % of
   frame height** → `exp(−1) ≈ 37`. At 1296 px tall, 3 % ≈ **39 px**.

   | mean_dev (1296 px frame) | position |
   |---|---|
   | 0 px | 100 |
   | ~10 px | ~92 |
   | ~20 px | ~77 |
   | ~39 px | ~37 |
   | ~78 px | ~14 |

2. **Coverage.** Linear multiplier — trace only half the line and the score
   halves, even if that half was perfect.

The exponential asymptotes: the score never reaches exactly 0 or exactly 100.

### Worked example

`mean_dev = 10 px`, `coverage = 95 %`, `frame_h = 1296`:

```
norm     = (10 / 1296) / 0.03 = 0.257
position = 100 · exp(−0.257)  = 77.3
accuracy = 77.3 · 0.95        = 73.4
```

If Stage 1 produced fewer than 3 scored slices, accuracy is `null` and a
`vision_no_score` / `vision_no_output` warning is added.

---

## 3. Stability

Computed from `imu.jsonl` (recorded START→STOP, ~150 Hz, gyro already
bias‑subtracted by the 2 s hold‑still at START). Function: `imu_stability`.

### Input

Per sample, angular‑speed magnitude:

```
ω = sqrt(gx² + gy² + gz²)      # deg/s, bias removed
```

### Reported metrics

| Field | Meaning | Scored? |
|---|---|---|
| `gyro_rms_deg_s` | RMS of ω — overall rotational activity | diagnostic |
| `peak_angular_velocity_deg_s` | max ω — worst instantaneous spin | diagnostic |
| `tremor_rms_deg_s` | high‑frequency jitter (below) | **drives the score** |

### Tremor (the stability driver)

Smooth, deliberate tracing must **not** count as instability — only jitter. So ω
is high‑pass filtered by subtracting its own moving average:

```python
fs   = samples / duration                    # ~150 Hz
half = fs * TREMOR_WIN_S / 2                  # TREMOR_WIN_S = 0.3 s
trend[i]    = mean(ω over [i-half, i+half])   # slow, intended motion
residual[i] = ω[i] − trend[i]                 # leftover high-freq tremor
tremor_rms  = sqrt(mean(residual²))           # deg/s
```

The ~0.3 s moving average is the intended trajectory; subtracting it removes the
low‑frequency motion of dragging the pen along the line and leaves the shakiness.
A still pen → `tremor_rms ≈ sensor noise (~0.1–0.3 °/s)`.

### Map to 0–100

```python
stability = round(100 * exp(-tremor_rms / TREMOR_TOL), 1)   # TREMOR_TOL = 6.0 deg/s
```

| tremor_rms | stability |
|---|---|
| 0 °/s | 100 |
| 3 °/s | ~61 |
| 6 °/s | ~37 |
| 12 °/s | ~14 |

(Measured: a still pen scored **98** at tremor 0.12 °/s.) If there are no IMU
samples, stability is `null` with a `no_imu_samples` warning.

### Limitations

- Boxcar high‑pass, not a true 4–12 Hz tremor bandpass — crude but effective.
- Uses **gyro only**; accelerometer (`ax/ay/az`) is recorded but unused.
- Moving average is index‑based (assumes ~uniform sample rate).
- `tremor_rms` has a small noise floor, so a perfectly still pen lands ~98.

---

## 4. Timing

```python
completion_time_seconds = (t_stop − t_go) / 1e9     # monotonic ns → s
```

`t_go` is set when recording starts (after IMU bias calibration); `t_stop` when
STOP is pressed. `duration_ms` in the run doc is the same interval in ms.

---

## 5. Quality fields (`compute_metrics`)

Transparency about how trustworthy a run is — never silently corrects data.

| Field | Meaning |
|---|---|
| `n_ref_slices` | slices with blue (reference length in slices) |
| `n_scored_slices` | slices scored (both colours) |
| `frame` | `[w, h]` of the scoring frame |
| `imu_samples_received` | valid IMU samples |
| `imu_samples_invalid` | failed reads (counted, never interpolated) |
| `imu_rate_hz` | effective sample rate over the run |
| `calibration_valid` | whether the START IMU bias cal succeeded |
| `warnings` | e.g. `vision_no_score`, `no_imu_samples`, `capture_*` |

---

## 6. Constants (tuning knobs)

| Constant | File | Default | Effect |
|---|---|---|---|
| `SLICE_PX` | server.py | 16 | vertical‑slice width (px) |
| `MIN_HITS` | rt_vision.cpp | 3 | subsampled pixels to trust a slice's colour |
| `DEV_TOL_FRAC` | server.py | 0.03 | accuracy strictness (mean dev as frac of frame height at ~37/100) |
| `TREMOR_WIN_S` | server.py | 0.3 | boundary between intended motion and tremor (s) |
| `TREMOR_TOL` | server.py | 6.0 | stability strictness (tremor °/s at ~37/100) |
| red/blue thresholds | rt_vision.cpp | see §1 | colour segmentation |

**Recommended calibration:** do one clean trace and one deliberately shaky
trace, then read the tiles — set `DEV_TOL_FRAC` from the clean run's
`mean deviation`, and `TREMOR_TOL` near the shaky run's `tremor`.

---

## 7. Output shapes

### `score.json` (per session, written by rt_vision)

```json
{
  "ok": true, "frame": [2304, 1296], "slice_px": 16,
  "n_ref_slices": 140, "n_scored_slices": 132, "coverage_pct": 94.3,
  "mean_dev_px": 9.8, "max_dev_px": 41.2, "rms_dev_px": 12.6, "ref_extent_px": 508.1,
  "reference": [[x, y], ...], "red": [[x, y], ...], "dev": [8.1, 9.0, ...]
}
```

### Run document (`session.json`, `outbox/latest.json`, and POSTed to the backend)

```json
{
  "schema_version": "2.1",
  "username": "alice",
  "session_id": "session_223031",
  "device_id": "qnx_pi_23",
  "task": {"type": "path_tracing", "version": "slice_v1"},
  "created_at": "2026-07-18T22:30:31Z",
  "timing": {"started_at": "…", "duration_ms": 12840},
  "scores": {"accuracy": 73.4, "stability": 98.0},
  "metrics": {
    "accuracy_score": 73.4, "mean_dev_px": 9.8, "max_dev_px": 41.2,
    "rms_dev_px": 12.6, "coverage_pct": 94.3, "completion_time_seconds": 12.8,
    "gyro_rms_deg_s": 4.1, "peak_angular_velocity_deg_s": 22.3,
    "tremor_rms_deg_s": 0.12, "stability_score": 98.0
  },
  "quality": { "...": "see §5" },
  "trace": {"frame": [2304, 1296], "reference": [[x, y], ...], "red": [[x, y], ...]}
}
```
