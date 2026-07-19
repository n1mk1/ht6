# Praxis — how the metrics are computed

Reference for every number a run produces: what it means, the exact formula, and
where it lives. Two deterministic score families — **accuracy** (from one
post-task photo) and **stability** (from the IMU stream) — each mapped onto a
**versioned global 0–100 scale** with named performance bands, plus timing,
quality, percentile and explanation fields.

| Layer | File | Role |
|---|---|---|
| Vision (pixels + scale bar) | `qnx/vision/rt_vision.cpp` `do_score` | detect blue/red/purple, per-slice centroids, px→mm |
| Deterministic metrics | `qnx/server/server.py` `compute_metrics` | perpendicular deviation, mm, tremor |
| **Versioned 0–100 scale + bands** | `qnx/praxis/score.py` | single source of truth (`praxis-score-1.0.0`) |
| Percentiles | `qnx/praxis/percentile.py` | rank vs a versioned reference set |
| Explanation | `qnx/praxis/explain.py` | LLM/template summary (never alters numbers) |

All scores are **prototype task-performance measures, not validated clinical
metrics.** They do not diagnose or grade any condition.

---

## 0. Pipeline at a glance

```
live view → START (IMU bias cal, then record IMU) → trace blue line in red
   → STOP (stop IMU + timer) → lift pen → CAPTURE & SCORE (one photo)
   → deterministic scoring → banding → percentile → explanation → save bundle
```

- The **camera** is untouched until CAPTURE & SCORE: one settled frame holds the
  printed **blue** reference, the **red** attempt, and the **purple** scale bar.
- The **IMU** records the whole START→STOP interval; stability comes from it.
- Order is strict: acquisition → scoring → stratification → **then** the LLM.

---

## 1. Colour detection (`rt_vision.cpp`)

Runs directly on NV12 Y/UV planes (no OpenCV). Four roles occupy four chroma
corners so they never bleed:

| Colour | Role | Rule (per pixel) | Defaults |
|---|---|---|---|
| **Red** | attempt | `Cr ≥ 150` and `Cb ≤ 128` and `Y ≥ 60` | red_v/u/y |
| **Blue** | reference | `Cb ≥ 150` and `Cr ≤ 120` and `Y ≥ 30` | blue_u/v/y |
| **Purple** | scale bar | `Cb ≥ 145` and `Cr ≥ 138` and `Y ≥ 30` | purple_u/v |

Purple = high Cb **and** high Cr, so it is clear of blue (low Cr), red (low Cb),
the green Pi PCB (low both) and near-neutral paper. Overridable on the CLI:
`--red-v`, `--blue-u`, `--blue-v`, `--purple-u`, `--purple-v`.

---

## 2. Scale → millimetres (fixed rig calibration)

The camera height and mat distance never change, so px→mm is a **one-time
constant**, `SCALE_PX_PER_MM` in `server.py` (currently **9.2**, from an 80 mm
purple bar measuring 736 px). There is **no per-run scale detection** — the
purple bar does not need to be in frame during runs.

**Recalibrate only if the rig moves:** place the 80 mm purple bar in frame and

```
./vision/rt_vision score --out /tmp/s.json --scale-mm 80
```

read `scale_px_per_mm`, and set `SCALE_PX_PER_MM` (constant or env var). The
`rt_vision` purple detection (`measure_scale_bar`: connected components, most
bar-shaped blob) exists only for this calibration step. **Accuracy is mm-based**
so scores are comparable across sessions.

---

## 3. Accuracy

### Stage 1 — per-slice centroids (`rt_vision.cpp`)
For a left→right pattern, the image is split into `SLICE_PX = 16` px vertical
slices. In each slice, blue and red each reduce to one centroid (≥ `MIN_HITS = 3`
subsampled pixels to count). Output: the `reference` and `red` centroid
polylines, plus `coverage_pct = 100 × n_scored_slices / n_ref_slices`
(under-tracing lowers coverage; blue-only slices are covered-but-unscored).

> The raw vertical-slice distance (`mean_dev_px` in `score.json`, kept as
> `slice_mean_dev_px`) is **not** the accuracy basis — it over-counts steep
> sections. See Stage 2.

### Stage 2 — perpendicular deviation, in mm (`server.py` `compute_metrics`)
The true curve-to-curve error is the **nearest-point (perpendicular) distance**
from each red centroid to the blue polyline — orientation-independent, so steep
peaks aren't penalised:

```python
perp[i]     = min distance from red_point[i] to any segment of the blue polyline
mean_dev_px = mean(perp);  max_dev_px = max(perp);  rms_dev_px = rms(perp)
mean_dev_mm = mean_dev_px / scale_px_per_mm          # requires the purple bar
```

### Stage 3 — map to 0–100 (`praxis/score.py` `accuracy_score`)
```python
ACC_TOL_MM = 5.0
position = 100 * exp(-mean_dev_mm / ACC_TOL_MM)      # closeness where traced
accuracy = round(position * (coverage_pct / 100), 1) # scaled by coverage
```

| mean_dev_mm | position | | coverage | multiplier |
|---|---|---|---|---|
| 0 mm | 100 | | 100 % | ×1.00 |
| 2 mm | ~67 | | 75 % | ×0.75 |
| 5 mm | ~37 | | 50 % | ×0.50 |
| 10 mm | ~14 | | | |

`accuracy` is `null` (never fabricated) if there are no scored slices or no scale
bar; a `vision_no_score` / `no_scale_bar_mm_unavailable` warning is added.

---

## 4. Stability

From `imu.jsonl` (recorded START→STOP, ~150–340 Hz, gyro bias-subtracted by the
2 s hold-still at START). Metrics in `server.py` `imu_stability`; score in
`praxis/score.py`.

Per sample angular speed `ω = sqrt(gx² + gy² + gz²)` (deg/s, bias removed).

| Field | Meaning | Scored? |
|---|---|---|
| `gyro_rms_deg_s` | RMS of ω (overall rotation) | diagnostic |
| `peak_angular_velocity_deg_s` | max ω | diagnostic |
| `tremor_rms_deg_s` | high-frequency jitter | **drives the score** |

**Tremor** isolates shakiness from intended motion by high-passing ω (subtract a
`TREMOR_WIN_S = 0.3 s` moving average = the intended trajectory; RMS of the
residual):

```python
stability = round(100 * exp(-tremor_rms_deg_s / STAB_TOL_DPS), 1)   # STAB_TOL_DPS = 6.0
```

| tremor_rms | stability |
|---|---|
| 0 °/s | 100 |
| 3 °/s | ~61 |
| 6 °/s | ~37 |
| 12 °/s | ~14 |

(A still pen ≈ 0.12 °/s → ~98.) `null` + `no_imu_samples` if the IMU stream is
empty. Limitations: boxcar high-pass (not a true 4–12 Hz bandpass); gyro only
(accel recorded, unused); index-based averaging assumes ~uniform rate.

---

## 5. Performance bands (`praxis/score.py`)

Five deterministic bands on the **0–100 score** (half-open, top closed at 100):

| Score | Band |
|---|---|
| 0–20 | very low |
| 20–40 | low |
| 40–60 | moderate |
| 60–80 | high |
| 80–100 | very high |

`None` score → `unknown`. Every session stores the full `score_definitions`
(version, formulas, tolerances, band cutoffs) so a result is always
interpretable against the exact scale that produced it. **Any change to a
formula/tolerance/band boundary MUST bump `SCORE_VERSION`.**

---

## 6. Percentiles (`praxis/percentile.py`)

A score is **not** a percentile. A percentile rank is computed **only** from a
real, versioned reference distribution, stratified by
`task_type / task_version / difficulty`:

```
percentile = 100 × (# reference scores ≤ this score) / N        # per stratum
```

- Needs a matching stratum with `N ≥ MIN_REFERENCE_N = 20`; otherwise
  `percentile = null` and the UI/summary show **"Percentile unavailable."**
- Never fabricated. Each result stores `reference_set_version`, `sample_count`,
  `population`, `is_prototype`.
- Prototype data is labeled **"prototype reference-set percentile"** (see the
  file in `praxis/reference_sets/`). Replace it with a real distribution
  collected via `PROTOCOL.md` before any non-prototype use.

---

## 7. Explanation (`praxis/explain.py`)

A user-facing summary only — it **never computes or changes a metric**. Runs
last, over a validated structured object (scores, bands, percentiles + ref-set
description, coverage, spatial error, completion time, smoothness, tremor,
quality warnings, task info).

- Tries **llama.cpp** (if `PRAXIS_LLAMA_BIN` + `PRAXIS_LLAMA_MODEL` are set):
  schema-constrained JSON output, a timeout, and **every number is validated
  against the source metrics** (a summary containing any unbacked number, or an
  altered score/band, is rejected).
- Falls back to a **deterministic template** on any failure/timeout/mismatch, or
  when llama is not configured. The template repeats scores, bands and
  percentiles exactly and lists the main contributing factors.
- Output: `{summary, source: "llama.cpp"|"template", validated, explain_version}`.

---

## 8. Timing & quality

```python
completion_time_seconds = (t_stop − t_go) / 1e9      # monotonic ns
```

Quality (`compute_metrics`), never silently corrected: `n_ref_slices`,
`n_scored_slices`, `frame`, `imu_samples_received`, `imu_samples_invalid`
(counted, never interpolated), `imu_rate_hz`, `calibration_valid`, `warnings`
(`vision_no_score`, `no_scale_bar_mm_unavailable`, `no_imu_samples`, `capture_*`).

---

## 9. Constants (tuning knobs)

| Constant | File | Default | Effect |
|---|---|---|---|
| `SLICE_PX` | server.py | 16 | vertical-slice width (px) |
| `SCALE_PX_PER_MM` | server.py | 9.2 | fixed rig px→mm (one-time calibration) |
| `MIN_HITS` | rt_vision.cpp | 3 | subsampled pixels to trust a slice's colour |
| `ACC_TOL_MM` | **praxis/score.py** | 5.0 | accuracy strictness (mean dev mm at ~37/100) |
| `TREMOR_WIN_S` | server.py | 0.3 | intended-motion vs tremor boundary (s) |
| `STAB_TOL_DPS` | **praxis/score.py** | 6.0 | stability strictness (tremor °/s at ~37/100) |
| `MIN_REFERENCE_N` | praxis/percentile.py | 20 | min samples for a valid percentile |
| red/blue/purple thresholds | rt_vision.cpp | §1 | colour segmentation |

Changing `ACC_TOL_MM` or `STAB_TOL_DPS` changes the scale → **bump
`SCORE_VERSION`**. Calibrating the bands/tolerances: see `PROTOCOL.md`.

---

## 10. Output shapes

### `score.json` (written by rt_vision)
```json
{
  "ok": true, "frame": [2304, 1296], "slice_px": 16,
  "n_ref_slices": 140, "n_scored_slices": 132, "coverage_pct": 94.3,
  "mean_dev_px": 9.8, "max_dev_px": 41.2, "rms_dev_px": 12.6, "ref_extent_px": 508.1,
  "scale_px_per_mm": 5.2, "scale_px": 640,
  "mean_dev_mm": 1.9, "max_dev_mm": 7.9, "rms_dev_mm": 2.4,
  "scale_bar": [[1328, 184], [1824, 184]],
  "reference": [[x, y], ...], "red": [[x, y], ...], "dev": [8.1, 9.0, ...]
}
```
> `mean_dev_px` in this file is the raw vertical-slice figure; the server
> recomputes the **perpendicular** deviation for scoring (§3 Stage 2).

### Run bundle (`session.json`, `outbox/latest.json`, POSTed to the web app)
```json
{
  "schema_version": "3.0",
  "username": "alice", "session_id": "session_223031", "device_id": "qnx_pi_23",
  "task": {"type": "path_tracing", "version": "mat_v1", "difficulty": 1},
  "created_at": "…", "timing": {"started_at": "…", "duration_ms": 12840},
  "scores": {
    "accuracy": 73.4, "stability": 98.0,
    "accuracy_band": "high", "stability_band": "very high",
    "version": "praxis-score-1.0.0"
  },
  "score_definitions": { "version": "praxis-score-1.0.0", "accuracy": {...},
                          "stability": {...}, "bands": [...] },
  "percentiles": {
    "accuracy":  {"percentile": 65.0, "reference_set_version": "proto-1",
                  "sample_count": 30, "is_prototype": true,
                  "label": "prototype reference-set percentile"},
    "stability": {"percentile": null, "label": "Percentile unavailable", "...": "…"}
  },
  "explanation": {"summary": "…", "source": "template", "validated": true,
                  "explain_version": "praxis-explain-1.0.0"},
  "metrics": { "accuracy_score": 73.4, "mean_dev_mm": 1.9, "coverage_pct": 94.3,
               "completion_time_seconds": 12.8, "gyro_rms_deg_s": 4.1,
               "tremor_rms_deg_s": 0.12, "stability_score": 98.0, "...": "…" },
  "quality": { "...": "see §8" },
  "trace": {"frame": [2304, 1296], "reference": [[x,y],...], "red": [[x,y],...],
            "scale_bar": [[1328,184],[1824,184]]},
  "artifacts": {"imu_jsonl": "imu.jsonl", "imu_bias": "imu_bias.json",
                "vision_score": "score.json", "end_image": "end.bmp",
                "preview_image": "preview.bmp"}
}
```
