from typing import Any

from fastapi import APIRouter, Request

from atlas_gemini_api import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": __version__,
        "environment": settings.app_env,
        "integrations": {
            "auth0": settings.auth0_configured,
            "mongodb": settings.mongodb_configured,
            "gemini": settings.gemini_configured,
        },
    }


@router.get("/ready")
async def ready(request: Request) -> dict[str, Any]:
    checks: dict[str, str] = {
        "auth0": "configured" if request.app.state.auth0 else "not_configured",
        "gemini": "configured" if request.app.state.gemini_client else "not_configured",
        "mongodb": "not_configured",
    }

    if request.app.state.mongo_database is not None:
        try:
            await request.app.state.mongo_database.command("ping")
            checks["mongodb"] = "ready"
        except Exception:
            checks["mongodb"] = "unavailable"

    return {
        "ready": all(value in {"configured", "ready"} for value in checks.values()),
        "checks": checks,
    }
