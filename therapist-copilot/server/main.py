"""FastAPI service for the RehabTrace Therapist Copilot (port 8003).

The Vite dev server proxies /copilot-api/* here.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .schemas import EditNoteRequest, IngestRun, ReviewItem
from .store import get_store
from .watcher import normalize_session, process_new_run, watch_backend

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("therapist_copilot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event = asyncio.Event()
    task = asyncio.create_task(watch_backend(stop_event))
    yield
    stop_event.set()
    await task


app = FastAPI(title="RehabTrace Therapist Copilot", version="1.0.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/copilot-api/health")
def health():
    store = get_store()
    return {
        "status": "ok",
        "mock_mode": get_settings().mock_mode,
        "runs_processed": len(store.processed_run_ids),
    }


@app.get("/copilot-api/inbox", response_model=list[ReviewItem])
def inbox():
    return get_store().list()


@app.post("/copilot-api/reviews/{review_id}/approve", response_model=ReviewItem)
def approve(review_id: str):
    store = get_store()
    item = store.get(review_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review not found")
    item.status = "approved"
    item.decision_log = [*item.decision_log, "Note approved by therapist."]
    store.update(item)
    return item


@app.post("/copilot-api/reviews/{review_id}/edit", response_model=ReviewItem)
def edit(review_id: str, body: EditNoteRequest):
    store = get_store()
    item = store.get(review_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review not found")
    item.draft_note = body.note
    item.status = "edited"
    item.decision_log = [*item.decision_log, "Note edited and approved by therapist."]
    store.update(item)
    return item


@app.post("/copilot-api/ingest", response_model=ReviewItem, status_code=201)
async def ingest(run: IngestRun):
    """Feed a run directly to the pipeline (demo/local mode, no backend needed).

    Direct ingests are compared against runs previously ingested for the same
    participant, kept in an in-memory cache for the life of the process.
    """
    payload = run.model_dump()
    if not (payload.get("id") or payload.get("session_id")):
        raise HTTPException(status_code=422, detail="Run needs an id or session_id")
    payload = normalize_session(payload)

    store = get_store()
    if store.has_processed(payload["id"]):
        raise HTTPException(status_code=409, detail="Run already processed")

    username = payload.get("username") or "anonymous"
    previous = [r for r in _ingested_runs if (r.get("username") or "anonymous") == username]
    item = await process_new_run(payload, previous)
    _ingested_runs.append(payload)
    return item


# Raw runs received via /ingest, kept for history comparison in demo mode.
_ingested_runs: list[dict] = []
