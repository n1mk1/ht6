from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_plugin import Auth0FastAPI
from google import genai
from pymongo import AsyncMongoClient

from atlas_gemini_api.config import Settings, get_settings
from atlas_gemini_api.routers import account, ai, health, notes


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.mongo_client = None
        app.state.mongo_database = None
        app.state.auth0 = None
        app.state.gemini_client = None

        if app_settings.mongodb_uri:
            mongo_client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
                app_settings.mongodb_uri,
                serverSelectionTimeoutMS=3_000,
            )
            app.state.mongo_client = mongo_client
            app.state.mongo_database = mongo_client[app_settings.mongodb_database]

        if app_settings.auth0_configured:
            app.state.auth0 = Auth0FastAPI(
                domain=app_settings.auth0_domain,
                audience=app_settings.auth0_audience or "",
                dpop_enabled=False,
            )

        if app_settings.gemini_api_key:
            app.state.gemini_client = genai.Client(api_key=app_settings.gemini_api_key)

        try:
            yield
        finally:
            if app.state.mongo_client is not None:
                await app.state.mongo_client.close()
            if app.state.gemini_client is not None:
                await app.state.gemini_client.aio.aclose()
                app.state.gemini_client.close()

    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if app_settings.app_env != "production" else None,
        redoc_url=None,
    )
    app.state.settings = app_settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(account.router, prefix="/api")
    app.include_router(notes.router, prefix="/api")
    app.include_router(ai.router, prefix="/api")

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"name": app_settings.app_name, "health": "/api/health", "docs": "/docs"}

    return app


app = create_app()
