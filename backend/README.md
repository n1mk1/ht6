# Praxis backend

The backend is an isolated FastAPI application. It does not import from or write
to `qnx/` or `freesolo/`. QNX sends its existing schema `3.0` session payload to
`POST /api/v1/qnx/sessions`; the current default `/api/runs` remains as a
compatibility alias.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/uvicorn praxis_api.main:app --reload --port 8000
```

SQLite migrations run at startup. The default database is `data/praxis.db`.
Set `BACKEND_URL=http://<host>:8000` and
`BACKEND_RUNS_PATH=/api/v1/qnx/sessions` on QNX.

FreeSOLO HTTP inference requires `PRAXIS_FREESOLO_MODEL` and
`PRAXIS_FREESOLO_API_KEY`. Until the current QNX payload supplies every metric
in the frozen FreeSOLO input contract, analysis is stored as `unavailable`.
`PRAXIS_FREESOLO_MODE=mock` is an explicit development-only simulation and is
rejected when `PRAXIS_ENVIRONMENT=production`.

The participant username is the current identity link between the dashboard and
QNX payloads. `POST /api/v1/users/resolve` performs a case-insensitive lookup or
creates an empty participant record so a user can sign in before their first
device run. This is not an authentication mechanism.

## API v1

- `POST /api/v1/qnx/sessions` - idempotent QNX schema `3.0` ingestion
- `GET /api/v1/users` and `GET|PATCH /api/v1/users/{id}` - profiles
- `POST /api/v1/users/resolve` - idempotently resolve or create a username
- `GET /api/v1/users/{id}/sessions` - history
- `GET /api/v1/users/{id}/sessions/latest` - latest result
- `GET /api/v1/users/{id}/trends` - chart series
- `GET /api/v1/users/{id}/comparisons/baseline` - earliest compatible baseline
- `GET /api/v1/sessions/{device_id}/{session_id}` - full run details
- `GET /api/v1/comparisons` - compatible pairwise comparison

## Persistence

Migration `001_initial.sql` creates:

- `users` for participant usernames and optional profile metadata;
- `tasks` for task type, version, difficulty, hand, and original task metadata;
- `sessions` for normalized scores, timing, movement, quality, trace fields,
  artifacts, and the complete original payload plus its SHA-256 digest;
- `deterministic_comparisons` for versioned compatible-run calculations; and
- `model_results` for FreeSOLO status and outputs, kept separate from
  deterministic comparisons.

Identical repeats of `(device_id, session_id)` return `200`. The first accepted
payload returns `201`; conflicting reuse returns non-retryable `409`, and schema
validation failures return `422`. QNX keeps its local run on all HTTP failures.

## Verification

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Tests cover schema `3.0`, payload preservation, idempotency, persistence,
compatible-run policy, username resolution, and the real and mock adapter
contracts.
