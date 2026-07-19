"""FastAPI service for the RehabTrace Gemini UI assistant.

Runs on its own port (default 8002) so the existing backend is untouched.
The Vite dev server proxies /assistant-api/* here.
"""

import logging
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .gemini_client import AssistantUpstreamError, ask_gemini, ask_mock
from .sanitize import context_to_prompt_block, sanitize_context
from .schemas import AskRequest, AskResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gemini_ui_assistant")

app = FastAPI(title="RehabTrace Gemini UI Assistant", version="1.0.0")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Simple in-memory sliding-window rate limiter, keyed by client IP.
_request_log: dict[str, deque[float]] = defaultdict(deque)


def _rate_limited(client_ip: str) -> bool:
    now = time.monotonic()
    window = get_settings().rate_limit_window_s
    log = _request_log[client_ip]
    while log and now - log[0] > window:
        log.popleft()
    if len(log) >= get_settings().rate_limit_requests:
        return True
    log.append(now)
    return False


@app.get("/health")
def health():
    return {"status": "ok", "mock_mode": get_settings().mock_mode}


@app.get("/assistant-api/health")
def assistant_health():
    return health()


@app.post("/assistant-api/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request) -> AskResponse:
    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"

    if _rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail="You are asking questions very quickly. Please wait a moment and try again.",
        )

    ctx = sanitize_context(body.ui_context)
    started = time.monotonic()

    if settings.mock_mode:
        answer = ask_mock(body.question, ctx)
        mock = True
    else:
        try:
            answer = await ask_gemini(body.question, context_to_prompt_block(ctx))
        except AssistantUpstreamError as err:
            logger.info(
                "ask failed status=upstream_error elapsed=%.2fs", time.monotonic() - started
            )
            raise HTTPException(status_code=502, detail=str(err)) from None
        mock = False

    # Cap the response length so the panel stays readable.
    if len(answer) > settings.max_answer_chars:
        answer = answer[: settings.max_answer_chars].rsplit(" ", 1)[0] + "…"

    # Log timing/status only — never question text or context data.
    logger.info(
        "ask ok mock=%s elapsed=%.2fs answer_chars=%d",
        mock,
        time.monotonic() - started,
        len(answer),
    )
    return AskResponse(answer=answer, mock=mock)
