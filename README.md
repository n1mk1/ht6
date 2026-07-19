# Praxis

Praxis is a prototype for measuring performance on a camera- and IMU-assisted
path-tracing task and reviewing changes across repeated sessions. A QNX device
captures each run, the web API stores and compares compatible runs, and a React
dashboard presents session history, measurements, trends, and model status.

> Praxis reports task-performance measurements. It is not a diagnostic device,
> and its scores and model outputs are not validated clinical conclusions.

## Architecture

```text
QNX device (qnx/)
  POST /api/v1/qnx/sessions, schema 3.0
                  |
                  v
FastAPI + MongoDB Atlas (backend/) --- HTTP adapter ---> FreeSOLO model (Modal)
                  |
                  v
React dashboard (frontend/) --+-- Therapist Copilot (therapist-copilot/, Gemini)
                              +-- UI Assistant      (gemini-ui-assistant/, Gemini)
```

The web application is isolated from the capture and model subsystems: it does
not import, move, or write into `qnx/` or `freesolo/`. The backend preserves
every accepted QNX payload unchanged in addition to storing normalized fields.
The two AI-teammate services run as separate processes and only read the
backend's public API.

| Directory | Purpose | Documentation |
|---|---|---|
| `qnx/` | QNX camera, IMU capture, deterministic scoring, and upload | [`qnx/README.md`](qnx/README.md) |
| `freesolo/` | Layered session-comparison model (SFT→GRPO) and training assets | [`freesolo/README.md`](freesolo/README.md) |
| `backend/` | Versioned ingestion and longitudinal REST API (MongoDB Atlas) | [`backend/README.md`](backend/README.md) |
| `frontend/` | Responsive participant session dashboard | [`frontend/README.md`](frontend/README.md) |
| `therapist-copilot/` | AI teammate: triages each session and drafts a note for therapist approval (Gemini) | [`therapist-copilot/README.md`](therapist-copilot/README.md) |
| `gemini-ui-assistant/` | Accessibility assistant: explains what is on screen in plain language (Gemini) | [`gemini-ui-assistant/README.md`](gemini-ui-assistant/README.md) |

The web application design and integration boundaries are described in
[`WEBAPP.md`](WEBAPP.md).

## Current functionality

- Captures a single post-task image containing a blue reference path and red
  attempt, plus IMU data collected during the task.
- Produces versioned deterministic accuracy and stability scores, timing,
  coverage, movement measurements, quality warnings, trace points, and local
  artifacts.
- Accepts QNX schema `3.0` payloads idempotently by `(device_id, session_id)`.
- Connects QNX and web sessions through the same case-insensitive username.
- Shows latest results, history, run details, trends, compatible baseline
  comparisons, and side-by-side comparisons.
- Attempts FreeSOLO analysis only through the backend adapter and clearly stores
  pending, unavailable, completed, or error status without inventing production
  predictions.
- Runs two optional AI teammates: a therapist copilot that triages each new
  session and drafts a note for approval, and an on-screen accessibility
  assistant. Both use Gemini when a key is set and fall back to deterministic
  templates otherwise.

## Quick start

Requirements: Python 3.11 or newer and Node.js 20 or newer.

Start the API:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env   # then set PRAXIS_MONGODB_URI to your Atlas connection string
.venv/bin/uvicorn praxis_api.main:app --reload --port 8000
```

In another terminal, start the dashboard:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The API health endpoint is
`http://localhost:8000/api/v1/health`, and interactive API documentation is at
`http://localhost:8000/docs`.

The opening page asks for a username. Use exactly the username entered before a
QNX run; matching ignores capitalization and surrounding spaces. A username is
currently a record identifier, **not authentication**. Do not expose this
prototype to sensitive or public use without adding real authentication and an
appropriate privacy/security review.

## Connect the QNX device

Deploy and open the device dashboard from the repository root:

```bash
cd qnx
make deploy
make dash
```

Set these variables in the QNX server environment before launch:

```bash
BACKEND_URL=http://<computer-lan-ip>:8000
BACKEND_RUNS_PATH=/api/v1/qnx/sessions
BACKEND_KEY=<optional-shared-device-key>
```

Use the backend computer's LAN address, not `localhost`, because the request
originates on the Pi. When `BACKEND_KEY` is set, it must match
`PRAXIS_DEVICE_KEY` in `backend/.env`. Failed uploads remain available in the
QNX local outbox; they do not delete the completed run.

## AI teammates (optional)

Two optional services enhance the dashboard. Both run in a deterministic mock
mode with no key, or with Gemini when `gemini_api_key` is set in each service's
`.env`. The frontend dev server proxies `/copilot-api` and `/assistant-api` to
them.

```bash
# Therapist copilot — triages sessions and drafts notes (reads the backend API)
cd therapist-copilot && pip install -r requirements.txt
BACKEND_URL=http://127.0.0.1:8000 uvicorn server.main:app --port 8003

# UI accessibility assistant
cd gemini-ui-assistant && pip install -r requirements.txt
uvicorn server.main:app --port 8002
```

## FreeSOLO status

The real integration boundary is `backend/src/praxis_api/freesolo.py`. The
adapter uses only fields emitted by QNX schema `3.0`, requires compatible task
and score versions, validates model semantics before persistence, and never
substitutes a fake regression score or confidence. An explicit mock exists only
for development and is rejected in production.

The deployed model is a layered adapter trained from `Qwen/Qwen3.5-4B` (SFT →
GRPO) and served over an OpenAI-compatible HTTPS endpoint on Modal; configure it
with `PRAXIS_FREESOLO_ENDPOINT`, `PRAXIS_FREESOLO_MODEL`, and
`PRAXIS_FREESOLO_API_KEY` in `backend/.env`. See
[`freesolo/LAYERED_MODEL.md`](freesolo/LAYERED_MODEL.md) for the model lineage,
[`freesolo/TRAINING_RUNS.md`](freesolo/TRAINING_RUNS.md) for auditable run
status, and [`WEBAPP.md`](WEBAPP.md) for integration behavior.

## Verification

Backend:

```bash
cd backend
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Frontend:

```bash
cd frontend
npm run lint
npm run test
npm run build
```

Existing subsystems:

```bash
python3 qnx/tests/test_praxis.py
python3 freesolo/scripts/demo.py
python3 freesolo/scripts/validate_dataset.py
```

Backend contract tests use the real QNX schema `3.0` fixture at
`backend/tests/fixtures/qnx_session_v3.json`.

## Data and services

Persistence is **MongoDB Atlas** via Motor (async driver); collection indexes are
created at API startup. Set `PRAXIS_MONGODB_URI` and `PRAXIS_MONGODB_DB` in
`backend/.env`. The **FreeSOLO** comparison model and the two **Gemini** AI
teammates are integrated in this revision; the AI teammates read the backend's
public API and fall back to deterministic behavior when no Gemini key is set.

Virtual environments, dependency directories, build outputs, and local `.env`
secrets are ignored by Git. Commit `.env.example` files only; never commit
credentials or participant data.
