# Praxis web application architecture

The web application lives in two isolated roots:

```text
QNX device --POST schema 3.0--> backend/ --JSON API--> frontend/
                                      |
                                      +--HTTP adapter--> FreeSOLO service
```

Neither application directory is imported by `qnx/` or `freesolo/`, and the
web application never writes into either subsystem. The backend retains the
unaltered QNX payload alongside normalized SQLite fields.

## Participant identity

The dashboard opens on a username entry screen. It resolves the username with
`POST /api/v1/users/resolve`; a new username creates an empty record, allowing
the participant to enter the dashboard before their first QNX session. QNX
payloads containing the same username are attached to that record. Lookup is
case-insensitive and trims surrounding whitespace.

This is session association only, not authentication or authorization. Auth0 is
not currently integrated, and this prototype should not be publicly exposed or
used for sensitive participant data in its present form.

## QNX boundary

The authoritative producer is `qnx/server/server.py`. It emits:

- schema version `3.0`;
- identity `(device_id, session_id)`;
- participant `username`;
- task `type`, `version`, and `difficulty`;
- timing, deterministic scores, metric values, quality, trace, percentiles,
  explanation, score definitions, and artifact pointers.

Configure the device with:

```bash
BACKEND_URL=http://<backend-host>:8000
BACKEND_RUNS_PATH=/api/v1/qnx/sessions
```

The existing `/api/runs` default is also accepted. A duplicate identical POST
returns `200`; the first accepted POST returns `201`. Reusing the same identity
for different content returns a clear non-retryable `409`. All other validation
errors use `422`. QNX keeps its local outbox on every HTTP failure.

The read API exposes participant profiles and history, latest session, trends,
run details, arbitrary compatible pairwise comparisons, and the earliest
compatible baseline comparison for a participant.

## FreeSOLO boundary

`backend/src/praxis_api/freesolo.py` is the only integration point. It builds
the versioned comparison input and calls the configured OpenAI-compatible deployed
endpoint. Responses are checked before persistence.

Contract `praxis-freesolo-2.0` uses the actual QNX accuracy/stability scores,
coverage, path-deviation measurements, completion time, tremor, peak angular
velocity, capture counts, calibration status, warnings, and score version. It
does not require legacy synthetic fields such as pause or correction counts.

The adapter independently recalculates directions, marks task/score-version or
capture-quality mismatches unreliable, and rejects semantically wrong,
ungrounded, or clinically unsafe model output. The output is qualitative, so
`regression_score` and `confidence` stay null for real responses.
`regression_flag` is only the transparent mapping of an accepted
`overall_pattern == declined` response. No v2 hosted run is considered active
until its ID and held-out evaluation are recorded in `freesolo/TRAINING_RUNS.md`.

## Local development

Backend:

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn praxis_api.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

The API documentation is available at `http://localhost:8000/docs`; the
dashboard is available at `http://localhost:5173`.

## Current infrastructure

The backend uses migration-managed SQLite. MongoDB Atlas and Gemini are not in
the current runtime path. They can be evaluated later without changing the QNX
schema: a database migration belongs behind the repository/service boundary,
and generated explanations belong behind a separate adapter that cannot alter
stored deterministic measurements.
