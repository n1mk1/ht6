# Gemini UI Assistant

A self-contained accessibility assistant for the RehabTrace dashboard. It helps
older adults understand what is currently on screen — page sections, metrics,
buttons, and warnings — in plain, respectful language.

It is an **interface guide, not a medical assistant**: it never interprets task
measurements as recovery or decline, never recommends treatment, and directs
clinical questions to the participant's therapist.

## How it works

```
Dashboard state ──contextBuilder.ts──► safe UI-context object
User question + context ──POST /assistant-api/ask──► FastAPI service (port 8002)
Service sanitizes the context, calls Gemini (or a local mock), validates the
answer, and returns it to the accessible assistant panel.
```

Everything lives in this folder. The only touch points with the existing app:

- `frontend/vite.config.ts` proxies `/assistant-api` to `http://localhost:8002`
- `frontend/src/App.tsx` renders `<AssistantPanel />` from this folder's `src/`

The Gemini API key stays on the server side. It is never sent to, or readable
from, the browser.

## Folder layout

```
gemini-ui-assistant/
├── README.md
├── .env.example        # template — copy to .env and add your key
├── .gitignore          # keeps .env out of Git
├── requirements.txt
├── server/             # FastAPI proxy service
│   ├── main.py         # app, CORS, /health, /assistant-api/ask
│   ├── config.py       # settings; no key -> mock mode
│   ├── schemas.py      # request/response models with size limits
│   ├── sanitize.py     # allowlist context filtering + PII stripping
│   ├── gemini_client.py# real Gemini client + local mock
│   └── system_prompt.py# the interface-guide system instruction
├── src/                # React pieces used by the dashboard
│   ├── AssistantPanel.tsx
│   ├── AssistantPanel.css
│   ├── contextBuilder.ts
│   └── assistantApi.ts
└── tests/
    ├── conftest.py
    ├── test_ask_route.py
    └── test_sanitize.py
```

## Setup

1. Create a virtual environment and install dependencies:

```bash
cd gemini-ui-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure the key (optional — skip for mock mode):

```bash
cp .env.example .env
# edit .env and set GEMINI_API_KEY to your real key
```

Never commit `.env`. It is ignored by this folder's `.gitignore` and the
repository root `.gitignore`.

## Run

Start the assistant service:

```bash
cd gemini-ui-assistant
source .venv/bin/activate
uvicorn server.main:app --reload --port 8002
```

Then start the dashboard as usual (`cd frontend && npm run dev`, port 5173).
The "Help me understand this screen" button appears at the bottom-right of the
dashboard after login.

### Mock mode (no API key needed)

If `GEMINI_API_KEY` is not set, the service answers with canned,
context-aware replies so the whole flow can be developed and demoed offline.
The panel shows a small "practice mode" note when this is active.

## Tests

```bash
cd gemini-ui-assistant
source .venv/bin/activate
python -m pytest tests/ -v
```

Tests cover request validation (empty input, max lengths), mock-mode answers,
Gemini timeout/failure handling, rate limiting, and context sanitization
(unknown keys dropped, tokens/names stripped, participant IDs anonymized).

## Privacy and safety

- Only a controlled context object is sent to Gemini: page name/title,
  visible section labels, metric labels/values/help text, and available
  action labels. Never the DOM, tokens, camera footage, IMU streams, or
  medical records.
- Participant usernames are replaced with an anonymous label server-side
  before anything reaches Gemini.
- Requests are validated, size-limited, timeout-protected, and rate limited.
- Logs record timing and status only — never question text or context data.
- The system instruction forbids diagnosis, recovery/decline interpretation,
  and treatment recommendations.
