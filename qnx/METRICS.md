# Praxis — how the metrics are computed

Reference for every number a run produces: what it means, the exact formula, and
where it lives. Two deterministic score families — **accuracy** (from one
post-task photo) and **stability** (from the IMU stream) — each mapped onto a
**versioned global 0–100 scale** with named performance bands, plus timing,
quality, percentile and explanation fields.

| Layer | File | Role |
|---|---|---|
| Vision (pixels) | `qnx/vision/rt_vision.cpp` `do_score` | detect blue/red, per-slice centroids |
| Deterministic metrics | `qnx/server/server.py` `compute_metrics` | perpendicular deviation, mm, tremor |
| **Versioned 0–100 scale + bands** | `qnx/praxis/score.py` | single source of truth (`praxis-score-1.1.0`) |
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
  printed **blue** reference and the **red** attempt.
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
mean_dev_mm = mean_dev_px / scale_px_per_mm          # fixed rig calibration
```

### Stage 3 — map to 0–100 (`praxis/score.py` `accuracy_score`)
```python
ACC_GOOD_MM = 1.86     # KatieCalibrationGood session_015856 -> 90
ACC_BAD_MM = 13.04     # katiecalibrationbad session_021311 -> 10
accuracy = linear_lower_is_better(mean_dev_mm, good=ACC_GOOD_MM, bad=ACC_BAD_MM)
```

Coverage remains a quality metric, but it does not multiply the score. The good
anchor had 72.4% detected coverage despite a visually accurate trace, so using
coverage as a multiplier made the score misleadingly low.

| mean_dev_mm | score |
|---|---|
| 0 mm | 100 |
| 1.86 mm | 90 |
| 13.04 mm | 10 |
| ≥14.44 mm | 0 |

`accuracy` is `null` (never fabricated) if there are no scored slices or if the
fixed rig scale is unavailable; a `vision_no_score` /
`scale_calibration_unavailable` warning is added.

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
STAB_GOOD_DPS = 5.18    # KatieCalibrationGood session_015856 -> 90
STAB_BAD_DPS = 35.91    # katiecalibrationbad session_021311 -> 10
stability = linear_lower_is_better(tremor_rms_deg_s, good=STAB_GOOD_DPS, bad=STAB_BAD_DPS)
```

| tremor_rms | stability |
|---|---|
| 0 °/s | 100 |
| 5.18 °/s | 90 |
| 35.91 °/s | 10 |
| ≥39.75 °/s | 0 |

(A still pen ≈ 0.12 °/s → 100.) `null` + `no_imu_samples` if the IMU stream is
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

- Tries official QNX **llama.cpp** using app-local defaults. The model selects
  one of two deterministic, grounded narrative candidates. A JSON grammar
  restricts the output to a valid candidate index, and **every number in the
  selected text is validated against the source metrics**.
- Falls back to a **deterministic template** on any failure/timeout/mismatch, or
  when llama is not configured. The template repeats scores, bands and
  percentiles exactly and lists the main contributing factors.
- Output: `{summary, source: "llama.cpp"|"template", validated,
  explain_version, model, inference_ms}`.

The image-quality classifier, QNX package layout, GGUF model, efficiency
settings, and fail-safe rationale are detailed in `AI_ARCHITECTURE.md`.

---

## 8. Timing & quality

```python
completion_time_seconds = (t_stop − t_go) / 1e9      # monotonic ns
```

Quality (`compute_metrics`), never silently corrected: `n_ref_slices`,
`n_scored_slices`, `frame`, `imu_samples_received`, `imu_samples_invalid`
(counted, never interpolated), `imu_rate_hz`, `calibration_valid`, `warnings`
(`vision_no_score`, `scale_calibration_unavailable`, `no_imu_samples`,
`capture_*`).

---

## 9. Constants (tuning knobs)

| Constant | File | Default | Effect |
|---|---|---|---|
| `SLICE_PX` | server.py | 16 | vertical-slice width (px) |
| `SCALE_PX_PER_MM` | server.py | 9.2 | fixed rig px→mm (one-time calibration) |
| `MIN_HITS` | rt_vision.cpp | 3 | subsampled pixels to trust a slice's colour |
| `ACC_GOOD_MM` / `ACC_BAD_MM` | **praxis/score.py** | 1.86 / 13.04 | accuracy anchors (90 / 10) |
| `TREMOR_WIN_S` | server.py | 0.3 | intended-motion vs tremor boundary (s) |
| `STAB_GOOD_DPS` / `STAB_BAD_DPS` | **praxis/score.py** | 5.18 / 35.91 | stability anchors (90 / 10) |
| `MIN_REFERENCE_N` | praxis/percentile.py | 20 | min samples for a valid percentile |
| red/blue/purple thresholds | rt_vision.cpp | §1 | colour segmentation |

Changing score anchors/formulas changes the scale → **bump
`SCORE_VERSION`**. Calibrating the bands/tolerances: see `PROTOCOL.md`.

---

## 10. Output shapes

### `score.json` (written by rt_vision)
```json
{
  "ok": true, "frame": [2304, 1296], "slice_px": 16,
  "n_ref_slices": 140, "n_scored_slices": 132, "coverage_pct": 94.3,
  "mean_dev_px": 9.8, "max_dev_px": 41.2, "rms_dev_px": 12.6, "ref_extent_px": 508.1,
  "scale_px_per_mm": null, "scale_px": 0,
  "mean_dev_mm": null, "max_dev_mm": null, "rms_dev_mm": null,
  "scale_bar": null,
  "reference": [[x, y], ...], "red": [[x, y], ...], "dev": [8.1, 9.0, ...]
}
```
> `mean_dev_px` in this file is the raw vertical-slice figure; the server
> recomputes the **perpendicular** deviation and converts it with the fixed
> `SCALE_PX_PER_MM` calibration for scoring (§3 Stage 2).

### Run bundle (`session.json`, `outbox/latest.json`, POSTed to the web app)
```json
{
  "schema_version": "3.0",
  "username": "alice", "session_id": "session_223031", "device_id": "qnx_pi_23",
  "task": {"type": "path_tracing", "version": "mat_v1", "difficulty": 1},
  "created_at": "…", "timing": {"started_at": "…", "duration_ms": 12840},
  "scores": {
    "accuracy": 90.0, "stability": 90.0,
    "accuracy_band": "very high", "stability_band": "very high",
    "version": "praxis-score-1.1.0"
  },
  "score_definitions": { "version": "praxis-score-1.1.0", "accuracy": {...},
                          "stability": {...}, "bands": [...] },
  "percentiles": {
    "accuracy":  {"percentile": 65.0, "reference_set_version": "proto-1",
                  "sample_count": 30, "is_prototype": true,
                  "label": "prototype reference-set percentile"},
    "stability": {"percentile": null, "label": "Percentile unavailable", "...": "…"}
  },
  "explanation": {"summary": "…", "source": "llama.cpp", "validated": true,
                  "explain_version": "praxis-explain-1.1.0",
                  "model": "SmolVLM-256M-Instruct-Q8_0.gguf",
                  "inference_ms": 596.7},
  "metrics": { "accuracy_score": 73.4, "mean_dev_mm": 1.9, "coverage_pct": 94.3,
               "completion_time_seconds": 12.8, "gyro_rms_deg_s": 4.1,
               "tremor_rms_deg_s": 0.12, "stability_score": 98.0, "...": "…" },
  "quality": {"image_quality": {"ok": true, "classification": "valid",
                "valid_probability": 0.9944, "repeat_recommended": false,
                "model_version": "praxis-image-quality-1.0.0",
                "inference_ms": 461.5}, "...": "see §8"},
  "trace": {"frame": [2304, 1296], "reference": [[x,y],...], "red": [[x,y],...]},
  "artifacts": {"imu_jsonl": "imu.jsonl", "imu_bias": "imu_bias.json",
                "vision_score": "score.json", "end_image": "end.bmp",
                "preview_image": "preview.bmp"}
}
```
