# QNX On-Device AI Architecture

## 1. Goal

Praxis keeps the original measurement workflow:

1. A QNX camera provides a live framing view.
2. The IMU is sampled continuously while the participant traces.
3. The participant stops and lifts the pen.
4. One final camera frame produces the deterministic accuracy score.
5. The recorded IMU samples produce the deterministic stability score.

AI is added around that workflow, not in place of it. The image-quality model
decides whether the final frame is usable, and QNX `llama.cpp` generates a
fact-grounded explanation. Neither model can change accuracy or stability.

This boundary is important for a cannot-fail embedded application. A model
failure can reduce convenience, but it cannot erase a run or silently change a
measurement.

## 2. Runtime data flow

```text
QNX libcamapi                     QNX I2C / MPU6050
      |                                  |
      | live preview                     | timestamped continuous samples
      v                                  v
rt_vision stream                  imu_recorder.py
      |                                  |
      | final BMP                        | imu.jsonl
      v                                  v
deterministic vision score        deterministic tremor score
      |                                  |
      +---------------+------------------+
                      |
                      v
             canonical session result
                      |
           +----------+----------+
           |                     |
           v                     v
 image-quality classifier   QNX llama.cpp generator
 valid / repeat warning     generated explanation
           |                     |
           +----------+----------+
                      v
              dashboard + session.json
```

The order is enforced in `server/server.py`: acquisition, deterministic
scoring, banding, percentile lookup, image validation, then explanation.

## 3. What runs on QNX

| Component | Artifact | Runtime | Purpose |
|---|---|---|---|
| Camera acquisition | `vision/rt_vision` | Native QNX C++ and `libcamapi` | Live preview and final BMP |
| Stability acquisition | `imu/imu_recorder.py` | QNX Python | Timestamped MPU6050 samples |
| Image-quality AI | `image_quality/model/quality_model.json` | Dependency-free QNX Python | Valid versus unusable final frame |
| Summary AI | `qwen2.5-0.5b-instruct-q4_k_m.gguf` | Official QNX `llama.cpp` package | Generate a plain-language session summary |
| Optional vision model | SmolVLM language model + projector | QNX `llama-mtmd-cli` | Secondary multimodal experiments, not the scoring path |

Everything runs on the Raspberry Pi 5. No frame, IMU sample, prompt, or result
is sent to a cloud inference service.

## 4. Real-time camera preview

`rt_vision stream` opens one QNX viewfinder and keeps it open. Every fresh NV12
frame is converted to a decimated 24-bit BMP and published with an atomic file
rename. The browser reloads that file every 160 ms, giving approximately six
visual updates per second for positioning the paper and camera.

This is a sequence of fresh frames rather than H.264 or MJPEG. BMP was retained
because it requires no codec package and uses the same tested QNX camera path as
scoring. The cost is higher network bandwidth. At the observed 576 x 324 output,
each frame is about 560 KB.

The persistent process is also a reliability improvement. The previous design
opened and closed the QNX viewfinder for every preview still, which could leave
the camera service in error 237. The server now owns exactly one stream process,
stops it before the full-resolution score capture, and cleans it up on shutdown.

## 5. Captured training dataset

The separate UI at `http://qnxpi23.local:8080/dataset` guided collection of 30
full-resolution BMPs. It is intentionally separate from the scoring dashboard
so training operations cannot alter a user run.

The labels describe image usability, not tracing skill:

| Label | Count | Included conditions |
|---|---:|---|
| `valid` | 10 | Five accurate and five inaccurate traces, all clear and fully framed |
| `invalid` | 20 | Blur, occlusion, framing errors, bad lighting, and wrong scenes |

Including inaccurate traces in the valid class is essential. Otherwise the
quality model could accidentally become a second accuracy scorer and bias the
deterministic metric.

Captured files live at:

```text
datasets/image_quality/data/
  captures/*.bmp
  labels.csv
  manifest.json
```

The image directory is gitignored and excluded from deployment deletion because
the raw set is about 272 MB. `labels.csv` and `manifest.json` preserve labels,
conditions, shot IDs, timestamps, and the collection plan. The trained model
stores this dataset SHA-256:

```text
1ff882a72cdf1e374a44003a54a0bf447d2b4363584ebb6782d305e9330fbbfd
```

## 6. Image-quality model

### 6.1 Why a small custom model

TensorFlow Lite was considered, including the QNX AI Camera reference project.
For this prototype, adding that runtime would require a larger toolchain and
deployment surface than the 30-image problem justified. A small regularized
classifier can run using only the QNX Python standard library and can be audited
end to end.

This is still a trained model. It is regularized logistic regression over image
features learned from the captured valid and invalid examples. It is not a set
of hand-written acceptance thresholds.

### 6.2 Feature extraction

`image_quality/features.py` parses uncompressed 24-bit BMP directly. It samples
every eighth pixel and divides the image into a 12 x 8 spatial grid. Each grid
cell contributes five values:

- luminance;
- chroma magnitude;
- red evidence;
- blue evidence;
- local edge strength.

Seven global values capture mean luminance, luminance variation, dark-pixel
fraction, bright-pixel fraction, red-pixel fraction, blue-pixel fraction, and
mean edge strength. The complete input has:

```text
12 x 8 x 5 + 7 = 487 features
```

The spatial grid lets the model learn framing, localized shadows, and occlusion.
The global values help distinguish blur, exposure failures, and wrong scenes.

### 6.3 Training

`image_quality/train.py` performs these steps:

1. Read `labels.csv` with Python's CSV parser.
2. Extract 487 features from every BMP.
3. Horizontally mirror each feature grid as augmentation.
4. Standardize each feature using training mean and standard deviation.
5. Fit balanced, L2-regularized logistic regression with gradient descent.
6. Evaluate a fixed condition-spanning holdout.
7. Refit the deployable model on all 30 images.
8. Write weights, normalization values, threshold, versions, provenance, and
   holdout results to `quality_model.json`.

Mirroring reduces dependence on whether glare or occlusion happened on the left
or right. Balanced class weights prevent the 20 invalid examples from dominating
the 10 valid examples.

### 6.4 Evaluation

The fixed holdout is shots 5, 10, 14, 18, 22, 26, and 30. It contains two valid
images and one image from each invalid condition family.

| Measure | Result |
|---|---:|
| Holdout accuracy | 0.8571, or 6/7 |
| Holdout balanced accuracy | 0.9000 |
| Valid recall | 1.0000 |
| Invalid recall | 0.8000 |

Shot 30, a heavy wrong-scene/occlusion example, was the missed holdout case and
received `0.6077` valid probability. This is a real limitation and is why the
classifier produces a warning rather than suppressing deterministic scores.

The final model fitted on all 30 examples reproduces all 30 labels. That is a
regression check, not an estimate of generalization. More independent sessions,
camera positions, users, lighting, and occlusion types are needed before the
probability can be interpreted as calibrated confidence.

On the QNX Pi, measured examples were:

| Capture | Valid probability | Decision | Inference |
|---|---:|---|---:|
| `001_valid_accurate.bmp` | 0.9944 | valid | 461.5 ms |
| `015_invalid_occlusion.bmp` | 0.0229 | invalid | 478.4 ms |

### 6.5 Runtime contract

The result is stored under `session.quality.image_quality`:

```json
{
  "ok": true,
  "model_version": "praxis-image-quality-1.0.0",
  "classification": "valid",
  "valid_probability": 0.9944,
  "repeat_recommended": false,
  "threshold": 0.5,
  "inference_ms": 461.5
}
```

A timeout, missing image, parser error, or missing model produces
`ai_image_quality_unavailable`. An invalid frame produces
`ai_image_quality_repeat_recommended`. In both cases, accuracy and stability
remain present because they were computed before this model ran.

## 7. QNX llama.cpp integration

### 7.1 Package and model

The runtime is the official QNX OSS `llama.cpp` package, version
`0.0.9006-r1`, built for QNX 8 aarch64. It is installed without root under:

```text
~/steadyeye/vendor/qnx-root/
```

The production summary model is the upstream Apache-2.0 Qwen2.5 0.5B Instruct
GGUF. It has approximately 0.49 billion parameters and is Q4_K_M quantized.
SmolVLM remains installed with its projector for optional multimodal
experiments, but it is not the summary generator:

| File | Bytes | SHA-256 |
|---|---:|---|
| `qwen2.5-0.5b-instruct-q4_k_m.gguf` | 491,400,032 | `74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db` |
| `SmolVLM-256M-Instruct-Q8_0.gguf` | 175,054,528 | `2a31195d3769c0b0fd0a4906201666108834848db768af11de1d2cef7cd35e65` |
| `mmproj-SmolVLM-256M-Instruct-Q8_0.gguf` | 103,769,856 | `7e943f7c53f0382a6fc41b6ee0c2def63ba4fded9ab8ed039cc9e2ab905e0edd` |

The 30 captured Praxis images do not train or fine-tune Qwen or SmolVLM. They
train only the image-quality classifier. Both language/vision-language models
are upstream pretrained models executed locally through `llama.cpp`.

### 7.2 Why the projector is not in the score path

The multimodal projector is installed so `llama-mtmd-cli` can be demonstrated
on-device and used for later secondary image inspection. It is not loaded for
normal scoring. Making a generative vision-language model the primary validity
gate would add latency, more memory, nondeterministic wording, and a second
image interpretation that is harder to calibrate from only 30 examples.

The custom classifier is faster, traceable, and trained on this exact camera.
Qwen therefore generates text only after all measurements and quality results
exist, where generation failure has no effect on those measurements.

### 7.3 Grounded summary generation

`praxis/explain.py` gives Qwen a compact structured record containing spatial
error, coverage, tremor, completion time, and quality warnings. Qwen generates
the central analytic sentence shown in the dashboard.
Deterministic code surrounds it with the exact score, image-decision, and
prototype-limitation sentences.

This is token-by-token text generation through `llama-completion`. There is no
candidate-summary list, classification label, retrieval step, ranking step, or
choice between prewritten responses. For example, the deployed QNX smoke test
generated this measurement-specific sentence from its supplied facts:

> The mean spatial error was 1.1 mm, pattern coverage was 98.4%, and tremor RMS
> was 0.7 deg/s.

Generation is bounded by several independent controls:

1. The prompt requests one concise analytic sentence and supplies only facts
   from the completed session.
2. Qwen generates that analysis using one to three measured factors.
3. Code adds both scores and bands as the exact first sentence.
4. Code adds the classifier decision as an exact sentence.
5. Code adds the exact prototype/non-diagnostic caveat as the final sentence.
6. A llama.cpp JSON schema restricts output to one bounded `analysis` string.
7. A dedicated analysis validator rejects invented numbers, extra sentences,
   unsupported qualitative thresholds, causal language, and comparisons.
8. `validate_summary` rejects every numeric value not present in the source
   object, altered scores or bands, a missing caveat, a wrong capture decision,
   and known unsupported medical claims.
9. Any process, timeout, parse, or validation failure uses the deterministic
   template.

The generated middle sentence is not a score input and cannot modify the
saved measurements. `source: "llama.cpp"` is reported only when generated prose
passes the complete validation contract.

### 7.4 QNX runtime details

An app-local QNX APK install needs two library settings:

```text
LD_LIBRARY_PATH=.../usr/lib/llama.cpp:.../usr/lib:/usr/lib:/lib
GGML_BACKEND_PATH=.../usr/lib/llama.cpp/libggml-cpu.so
```

`LD_LIBRARY_PATH` resolves shared libraries. `GGML_BACKEND_PATH` is separately
required because current `llama.cpp` dynamically loads its CPU compute backend.
Without it, the executable starts but reports that no backends are loaded.

The deployed command uses:

| Setting | Value | Reason |
|---|---:|---|
| Executable | `llama-completion` | Avoid interactive chat-wrapper overhead |
| Model | Qwen2.5 0.5B Instruct Q4_K_M | Better instruction following with bounded Pi memory |
| Context | 1,024 tokens | Holds the compact facts and one generated analysis sentence without the full 32K model context |
| Generation limit | 120 tokens | Enough for a 20-45 word analysis with a hard upper bound |
| Temperature / top-p | 0.2 / 0.9 | Low variation without forcing identical wording |
| Threads | 3 | Leaves one Pi core available for the server and OS |
| Priority | low (`--prio -1`) | AI must not compete with acquisition |
| Polling | disabled (`--poll 0`) | Avoid busy-wait CPU use |
| Log verbosity | 0; performance report disabled | Do not capture unused model diagnostics |
| Repetition penalty | 1.12 over 128 tokens | Reduce repeated clauses in generated prose |
| Warmup | disabled | One generation per completed run |
| Auto-fit | disabled | Model and context sizes are already bounded |
| Vision projector | disabled/not loaded | Not needed for text generation |

End-to-end Python timing is exposed in the UI and session JSON because model
load, prompt evaluation, generation length, and device load can vary. Summary
generation intentionally takes longer than the image-quality classifier and is
run only after acquisition and deterministic scoring are finished.

### 7.5 Latency optimization process

The final command was reached through measurement rather than choosing flags in
advance. The progression is useful because each step exposed a different cost:

| Iteration | Observed behavior | Engineering change |
|---|---|---|
| App-local binary with only `LD_LIBRARY_PATH` | Model failed with `no backends are loaded` | Point `GGML_BACKEND_PATH` at the packaged `libggml-cpu.so` |
| Vision-language model's 135M text backbone | Generated prose but weak instruction following | Use the dedicated Qwen2.5 0.5B Instruct text model |
| Interactive `llama-cli` | Added terminal/chat wrapper overhead | Use non-interactive `llama-completion -no-cnv` with an explicit ChatML prompt |
| Unbounded plain-text response | Harder to extract and could run too long | Enforce a bounded JSON `analysis` schema and 120-token limit |
| Full session object in the prompt | More prompt-evaluation work and irrelevant fields | Send a compact allowlist of explanation facts |
| Full model context | Unnecessary KV-cache allocation | Limit context to 1,024 tokens |
| Default scheduling | AI could consume every available core | Use three threads, low priority, and no polling |
| Default diagnostic output | Thousands of unused model-detail characters captured by Python | Set verbosity to zero and disable the performance report while preserving generated JSON |

The main lessons were:

- **Backend discovery and shared-library discovery are different.** The binary
  can start successfully while inference still cannot find a compute backend.
- **Prompt evaluation is part of latency.** Sending only explanation-relevant
  fields reduces work and prevents unrelated session data influencing prose.
- **Output length matters twice.** Longer text takes more token evaluation and
  gives a small model more opportunities to repeat or omit facts.
- **The interface matters.** `llama-cli` includes an interactive chat wrapper;
  `llama-completion -no-cnv` is a better fit for one-shot embedded generation.
- **Grammar is not factual validation.** JSON schema guarantees shape, while a
  separate validator checks the generated meaning against source measurements.
- **Measure internal and external time separately.** SSH command wall time
  includes connection setup and is not the device inference latency. The UI
  records timing around the local subprocess on the Pi.

A persistent `llama-server` could remove model reload entirely, but it would
reserve memory continuously and add another daemon to supervise. Since inference
runs once after a completed session and the model itself loads in roughly 0.15
seconds, one isolated process per run is currently the better reliability and
resource tradeoff.

## 8. Reliability and scheduling

The architecture uses QNX isolation rather than assuming AI is reliable:

- IMU collection runs before any AI process starts.
- Final camera scoring completes before `llama.cpp` starts.
- The classifier has a 12-second subprocess deadline.
- `llama.cpp` has a 75-second deadline and low CPU priority.
- The LLM receives no control over hardware, scores, files, or network.
- Every generated analysis is schema-constrained and numerically validated.
- Every session is saved locally even if backend forwarding fails.
- AI errors are visible quality state, never silent score replacement.

For a stricter production real-time system, acquisition and scoring would move
into dedicated QNX processes with explicit scheduling priorities and message
passing. This prototype already respects that ordering but still uses a Python
control server for development speed.

## 9. Frontend behavior

The dashboard makes the AI boundary visible:

- The camera panel shows `CONNECTING`, `LIVE`, `CAPTURING`, or `CAPTURED`.
- The image gate shows accepted/repeat status, valid probability, model version,
  QNX CPU execution, and classifier latency.
- The analysis panel shows `QNX llama.cpp`, the model name, measured latency,
  and `fact-validated` when generated text passes validation.
- If llama fails, the same panel says `deterministic fallback`.
- If image validation fails, the UI still shows accuracy and stability and asks
  for a repeat rather than hiding data.

## 10. Build, train, and deploy

```bash
cd qnx

# Capture and retrieve labeled BMPs
make dataset
make pull-dataset

# Train the small quality model on the host
make ai-train

# Install official QNX llama.cpp app-locally
make ai-install

# Verify checksums and copy GGUF files separately
make ai-models

# Build rt_vision, sync code, and restart the QNX server
make deploy

# Or run the complete sequence
make ai
```

Normal `make deploy` excludes `models/`, `vendor/`, and captured dataset data.
This prevents `rsync --delete` from deleting the app-local QNX runtime, large
GGUF artifacts, or collected images.

Tests:

```bash
python3 tests/test_praxis.py
python3 tests/test_image_quality.py
python3 tests/test_outbox.py

# On the QNX Pi, with llama.cpp and the Qwen model installed
~/venv/bin/python tests/smoke_llama.py
```

`test_image_quality.py` always checks model versions and dimensions. When raw
captures are present, it also checks all files, feature extraction, probability
bounds, mirror invariants, and final-model label reproduction.

## 11. Important tradeoffs

| Decision | Benefit | Cost / limitation |
|---|---|---|
| Deterministic scores remain authoritative | Reproducible and fail-safe | AI cannot correct a flawed scoring formula |
| Small logistic classifier | Auditable, no runtime dependency, camera-specific | Limited capacity and only 30 examples |
| Hand-designed image features | Fast and explainable | May miss novel scene failures a CNN would learn |
| Train final model on all 30 | Uses scarce data | Training-label accuracy is not generalization evidence |
| Fixed 0.5 threshold | Simple contract | Probability is not calibrated on a large independent set |
| Q4_K_M Qwen 0.5B | Stronger instruction following within bounded Pi memory | More latency and memory than the smaller SmolVLM text backbone |
| LLM generates grounded analysis inside invariant framing | Useful and visibly generative while mandatory facts stay exact | Higher latency and possible fallback when validation rejects prose |
| Start llama per completed run | Strong isolation and simple cleanup | Repeated model/process startup latency |
| Keep multimodal projector optional | Protects score latency and memory | VLM is not the primary image validator |
| Rootless app-local APK install | Reproducible without administrator access | Must manage library/backend paths manually |
| BMP live frames | No extra codec dependency | Higher bandwidth and about six updates per second |

## 12. Prize-track mapping

**Product uses QNX OS:** camera acquisition, IMU acquisition, scoring control,
quality inference, `llama.cpp`, storage, and the web server all run on QNX 8 on
the Raspberry Pi 5.

**Includes a QNX open-source AI module:** the official QNX OSS `llama.cpp`
package executes the local GGUF model.

**Cannot-fail application:** measurements are completed and persisted before
optional generative AI. Deadlines, process isolation, grammar, validation, and
deterministic fallback bound failures.

**Requires real-time and reliability:** continuous timestamped IMU acquisition
and a persistent low-latency camera view are the real-time inputs. AI is
deliberately scheduled after acquisition at low priority.

**Interesting use of AI:** a camera-specific learned quality gate catches
unusable measurements, while an embedded LLM generates a validated explanation
without gaining authority over the measurement.

**No cloud:** all model files and inference processes are local to the QNX Pi.

## 13. Limitations and next data

This is a prototype and not a clinical or diagnostic system. The most important
next step is an independent evaluation set captured on different days without
reusing training scenes. Collect at least 20-30 new images per major failure
condition, especially partial occlusion and wrong scenes. Then choose the
threshold from the false-accept cost, not from training accuracy.

If more varied data becomes available, a small quantized CNN through a supported
QNX inference runtime could replace logistic regression. The current model is
the lower-risk choice for the available data and schedule, not a claim that
logistic regression is universally superior.

## 14. Primary references

- QNX OSS package dashboard: <https://oss.qnx.com/?search=llama.cpp>
- QNX AI Camera reference project: <https://gitlab.com/qnx/projects/ai-camera-app>
- QNX TensorFlow port files: <https://github.com/qnx-ports/build-files/tree/main/ports/tensorflow>
- llama.cpp CLI documentation: <https://github.com/ggml-org/llama.cpp/blob/master/tools/cli/README.md>
- Qwen2.5 0.5B Instruct GGUF: <https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF>
- SmolVLM GGUF model: <https://huggingface.co/ggml-org/SmolVLM-256M-Instruct-GGUF>
