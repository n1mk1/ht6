# Therapist Copilot

An AI teammate for the physiotherapist using Praxis. When a new session
arrives from the device, the copilot automatically:

1. **Triages data quality** — checks calibration, IMU sample counts, and
   warnings, and flags sessions that should be redone (rule-based, no LLM).
2. **Compares with history** — computes each metric's change against the
   participant's own recent average (arithmetic, no LLM).
3. **Drafts a progress note** — Gemini writes a short factual note for the
   therapist to approve or edit. It describes task performance only; it never
   interprets results as recovery or decline.
4. **Prioritizes the worklist** — "Needs attention" (data problem),
   "Review" (notable metric change), or "Routine".

Every step is recorded in a human-readable **decision log**, and nothing is
final until the therapist clicks Approve. The result: minutes of repetitive
review and documentation per session become a one-click approval.

## How it connects

```
QNX Pi ──POST /api/v1/sessions──► Praxis API (:8000)
therapist-copilot (:8003) ──polls /api/v1/users + sessions every 5s──► new runs
        │ pipeline: quality gate → history compare → note draft → priority
        ▼
"Therapist inbox" view in the dashboard ──approve / edit──► copilot store
```

The copilot only *reads* from the Praxis API over HTTP. It never writes to the
backend database and requires no changes to the backend or the Pi.

## Folder layout

```
therapist-copilot/
├── README.md
├── .env.example         # copy to .env; works fully without a key (mock notes)
├── .gitignore
├── requirements.txt
├── server/
│   ├── main.py          # FastAPI app: inbox, approve/edit, ingest, health
│   ├── config.py        # settings; no GEMINI_API_KEY -> mock note writer
│   ├── watcher.py       # background poller for new sessions on the Praxis API
│   ├── pipeline.py      # quality gate, history comparison, priority, decision log
│   ├── note_writer.py   # Gemini note drafting + deterministic mock
│   ├── store.py         # JSON-file review store (data/reviews.json)
│   └── schemas.py       # review item and API models
├── src/
│   ├── TherapistInbox.tsx   # dashboard view: worklist, notes, approve/edit
│   └── TherapistInbox.css
└── tests/
    ├── conftest.py
    ├── test_pipeline.py
    └── test_api.py
```

## Setup

```bash
cd therapist-copilot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional; only needed to set a real GEMINI_API_KEY
```

## Run

```bash
uvicorn server.main:app --reload --port 8003
```

- With the Praxis API running (`:8000`), the copilot picks up new sessions
  automatically within ~5 seconds.
- Without the backend, you can feed it sessions directly (used for demos and
  local testing):

```bash
curl -X POST http://localhost:8003/copilot-api/ingest \
  -H 'Content-Type: application/json' \
  -d @tests/fixtures/sample_run.json
```

Then open the dashboard (`cd frontend && npm run dev`, port 5173) — the
**Therapist inbox** view in the sidebar shows the processed session.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/copilot-api/health` | status + mock mode + runs processed |
| GET | `/copilot-api/inbox` | review items, newest first |
| POST | `/copilot-api/reviews/{id}/approve` | mark a draft note approved |
| POST | `/copilot-api/reviews/{id}/edit` | replace the note text (auto-approves) |
| POST | `/copilot-api/ingest` | feed a run directly (demo/local mode) |

## Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

## Safety and privacy

- Quality and priority decisions are deterministic rules — auditable and
  reproducible, never model output.
- Gemini sees only metric labels/values and deltas, with participants
  identified by anonymous IDs (P-1, P-2, ...). No names, no tokens, no raw
  camera/IMU data.
- Drafted notes describe task performance only. The system prompt forbids
  diagnosis, recovery/decline claims, and treatment recommendations.
- Nothing is published without therapist approval, and every agent action is
  visible in the per-session decision log.
