"""Ingest + read tracing runs from the QNX device.

The device POSTs a run document tagged with a participant `username`; it is
stored in the `runs` MongoDB collection with a server-side `received_at`.
Reading runs back requires an authenticated user (the webapp)."""
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from atlas_gemini_api.dependencies import (
    get_runs_collection,
    require_device,
    require_user,
)
from atlas_gemini_api.models import RunIngest

router = APIRouter(prefix="/runs", tags=["runs"])
RunsCollection = Annotated[Any, Depends(get_runs_collection)]
CurrentUser = Annotated[dict[str, Any], Depends(require_user)]


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_device)])
async def ingest_run(payload: RunIngest, collection: RunsCollection) -> dict[str, Any]:
    document = payload.model_dump()
    document["username"] = document["username"].strip()
    document["received_at"] = datetime.now(UTC)
    result = await collection.insert_one(document)
    return {"ok": True, "id": str(result.inserted_id)}


@router.get("")
async def list_runs(
    user: CurrentUser,
    collection: RunsCollection,
    username: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    query = {"username": username} if username else {}
    cursor = collection.find(query).sort("received_at", -1).limit(limit)
    documents = await cursor.to_list(length=limit)
    for document in documents:
        document["_id"] = str(document["_id"])
    return documents
