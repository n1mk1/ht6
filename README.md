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
FastAPI + SQLite (backend/) ---- narrow HTTP adapter ----> FreeSOLO service
                  |
                  v
React dashboard (frontend/)
```

The web application is isolated from both existing subsystems: it does not
import, move, or write into `qnx/` or `freesolo/`. The backend preserves every
accepted QNX payload unchanged in addition to storing normalized fields.

| Directory | Purpose | Documentation |
|---|---|---|
| `qnx/` | QNX camera, IMU capture, deterministic scoring, and upload | [`qnx/README.md`](qnx/README.md) |
| `freesolo/` | Versioned performance-comparison model contract and training assets | [`freesolo/README.md`](freesolo/README.md) |
| `backend/` | Versioned ingestion and longitudinal REST API | [`backend/README.md`](backend/README.md) |
| `frontend/` | Responsive participant session dashboard | [`frontend/README.md`](frontend/README.md) |

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

## Quick start

Requirements: Python 3.11 or newer and Node.js 20 or newer.

Start the API:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
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

## FreeSOLO status

The real integration boundary is `backend/src/praxis_api/freesolo.py`. Contract
`praxis-freesolo-2.0` uses only fields emitted by QNX schema `3.0`. The adapter
requires compatible task and score versions, validates model semantics before
persistence, and never substitutes a fake regression score or confidence. An
explicit mock exists only for development and is rejected in production.

No v2 hosted adapter is recorded as trained or deployed yet. See
[`freesolo/TRAINING_RUNS.md`](freesolo/TRAINING_RUNS.md) for the auditable run
status and [`WEBAPP.md`](WEBAPP.md) for integration behavior.

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

The current local database is SQLite at `backend/data/praxis.db`; migrations run
automatically at API startup. Auth0, MongoDB Atlas, and Gemini are possible
future integrations but are **not implemented in this revision**. The README
states the deployed code path rather than sponsor-service plans.

Generated databases, virtual environments, dependency directories, build
outputs, and local `.env` secrets are ignored by Git. Commit `.env.example`
files only; never commit credentials or participant data.
