"""Background poller: watches the Praxis API for new sessions and feeds them
through the pipeline. If the backend is down, it retries quietly — the
copilot's own API (and direct /ingest) keep working regardless."""

import asyncio
import logging

import httpx

from .config import get_settings
from .note_writer import draft_note
from .pipeline import process_run
from .store import get_store

logger = logging.getLogger("therapist_copilot")


async def _fetch_json(client: httpx.AsyncClient, url: str):
    resp = await client.get(url, timeout=6)
    resp.raise_for_status()
    return resp.json()


def normalize_session(session: dict) -> dict:
    """Adapt a Praxis API v1 session document to the pipeline's expectations:
    a stable string id and a top-level username."""
    run = dict(session)
    device = run.get("device_id") or "unknown_device"
    sid = run.get("session_id") or run.get("id") or "unknown"
    run["id"] = f"{device}::{sid}"
    user = run.get("user") or {}
    run["username"] = user.get("username") or run.get("username") or "anonymous"
    if not run.get("received_at"):
        run["received_at"] = run.get("created_at") or ""
    return run


async def process_new_run(run: dict, previous_runs: list[dict]):
    store = get_store()
    item = process_run(run, previous_runs, store.participant_ids)
    note, is_mock = await draft_note(item, run)
    item.draft_note = note
    item.note_is_mock = is_mock
    store.add(item)
    logger.info(
        "processed run=%s participant=%s priority=%s quality=%s",
        item.run_id,
        item.participant_id,
        item.priority,
        item.quality_verdict,
    )
    return item


async def poll_backend_once(client: httpx.AsyncClient) -> int:
    """Fetch sessions per user from the Praxis API, process unseen ones."""
    settings = get_settings()
    store = get_store()
    base = settings.backend_url.rstrip("/")

    users = await _fetch_json(client, f"{base}/api/v1/users")
    processed = 0
    for user in users:
        try:
            sessions = await _fetch_json(
                client, f"{base}/api/v1/users/{user['id']}/sessions"
            )
        except httpx.HTTPError:
            logger.warning(
                "could not fetch sessions for user %s; will retry next poll",
                user.get("id"),
            )
            continue

        runs = [normalize_session(s) for s in sessions]
        # Oldest first so history comparisons see earlier sessions.
        runs.sort(key=lambda r: r.get("received_at") or "")

        for idx, run in enumerate(runs):
            if store.has_processed(run["id"]):
                continue
            history = list(reversed(runs[:idx]))  # newest previous session first
            await process_new_run(run, history)
            processed += 1
    return processed


async def watch_backend(stop_event: asyncio.Event):
    settings = get_settings()
    backend_was_up = True
    async with httpx.AsyncClient() as client:
        while not stop_event.is_set():
            try:
                await poll_backend_once(client)
                if not backend_was_up:
                    logger.info("backend reachable again at %s", settings.backend_url)
                    backend_was_up = True
            except httpx.HTTPError:
                if backend_was_up:
                    logger.info(
                        "backend not reachable at %s — will keep retrying quietly",
                        settings.backend_url,
                    )
                    backend_was_up = False
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=settings.poll_interval_s
                )
            except asyncio.TimeoutError:
                pass
