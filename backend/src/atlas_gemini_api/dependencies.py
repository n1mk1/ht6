from typing import Any

from fastapi import HTTPException, Request, status


async def require_user(request: Request) -> dict[str, Any]:
    auth0 = request.app.state.auth0
    if auth0 is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth0 is not configured. Set AUTH0_DOMAIN and AUTH0_AUDIENCE.",
        )

    dependency = auth0.require_auth()
    return await dependency(request)


def get_notes_collection(request: Request) -> Any:
    database = request.app.state.mongo_database
    if database is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB is not configured. Set MONGODB_URI.",
        )
    return database.get_collection("notes")


def get_gemini_client(request: Request) -> Any:
    client = request.app.state.gemini_client
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini is not configured. Set GEMINI_API_KEY.",
        )
    return client
