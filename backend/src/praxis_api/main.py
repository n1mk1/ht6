from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .db import Database
from .freesolo import FreeSoloAdapter
from .schemas import QnxSessionPayload, UserResolve, UserUpdate
from .service import PraxisService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = Database(settings.database_path)
    service = PraxisService(database, FreeSoloAdapter(settings))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        database.migrate()
        yield

    app = FastAPI(
        title="Praxis API",
        version="1.0.0",
        description="Versioned QNX ingestion and longitudinal task-performance API",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "X-Device-Key"],
    )

    def require_device(x_device_key: str | None = Header(default=None)) -> None:
        if settings.device_key and not (
            x_device_key and secrets.compare_digest(x_device_key, settings.device_key)
        ):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=401,
                detail={"code": "invalid_device_key", "retryable": False},
            )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "api_version": "v1"}

    async def ingest(
        request: Request,
        payload: QnxSessionPayload,
        response: Response,
        background_tasks: BackgroundTasks,
    ) -> dict:
        original_payload = await request.json()
        session, created = service.ingest(payload, original_payload)
        if created:
            background_tasks.add_task(service.analyze_session, session["id"])
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return {
            "ok": True,
            "created": created,
            "session": {
                "id": session["id"],
                "session_id": session["session_id"],
                "device_id": session["device_id"],
            },
            "model_status": session["model_result"]["status"],
        }

    app.post("/api/v1/qnx/sessions", dependencies=[Depends(require_device)])(ingest)
    # Compatibility route for the current QNX BACKEND_RUNS_PATH default.
    app.post("/api/runs", dependencies=[Depends(require_device)], include_in_schema=False)(ingest)

    @app.get("/api/v1/users")
    def users() -> list[dict]:
        return service.list_users()

    @app.post("/api/v1/users/resolve")
    def resolve_user(request: UserResolve, response: Response) -> dict:
        user, created = service.resolve_user(request)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return {"created": created, "user": user}

    @app.get("/api/v1/users/{user_id}")
    def user(user_id: int) -> dict:
        return service.get_user(user_id)

    @app.patch("/api/v1/users/{user_id}")
    def update_user(user_id: int, update: UserUpdate) -> dict:
        return service.update_user(user_id, update)

    @app.get("/api/v1/users/{user_id}/sessions")
    def sessions(
        user_id: int,
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict]:
        return service.list_sessions(user_id, limit, offset)

    @app.get("/api/v1/users/{user_id}/sessions/latest")
    def latest(user_id: int) -> dict:
        return service.latest(user_id)

    @app.get("/api/v1/users/{user_id}/trends")
    def trends(user_id: int, limit: int = Query(default=50, ge=1, le=200)) -> dict:
        return service.trends(user_id, limit)

    @app.get("/api/v1/users/{user_id}/comparisons/baseline")
    def baseline_comparison(
        user_id: int,
        current_device_id: str | None = None,
        current_session_id: str | None = None,
    ) -> dict:
        return service.baseline_comparison(user_id, current_device_id, current_session_id)

    @app.get("/api/v1/sessions/{device_id}/{session_id}")
    def session(device_id: str, session_id: str) -> dict:
        return service.get_session(device_id, session_id)

    @app.get("/api/v1/comparisons")
    def comparison(
        reference_device_id: str,
        reference_session_id: str,
        current_device_id: str,
        current_session_id: str,
    ) -> dict:
        return service.compare(
            reference_device_id,
            reference_session_id,
            current_device_id,
            current_session_id,
        )

    return app


app = create_app()
