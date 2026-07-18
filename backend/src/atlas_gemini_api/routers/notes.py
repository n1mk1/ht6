from datetime import UTC, datetime
from typing import Annotated, Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Response, status

from atlas_gemini_api.dependencies import get_notes_collection, require_user
from atlas_gemini_api.models import Note, NoteCreate

router = APIRouter(prefix="/notes", tags=["notes"])
CurrentUser = Annotated[dict[str, Any], Depends(require_user)]
NotesCollection = Annotated[Any, Depends(get_notes_collection)]


def to_note(document: dict[str, Any]) -> Note:
    return Note(
        id=str(document["_id"]),
        title=document["title"],
        content=document.get("content", ""),
        created_at=document["created_at"],
    )


@router.get("", response_model=list[Note])
async def list_notes(
    user: CurrentUser,
    collection: NotesCollection,
) -> list[Note]:
    cursor = collection.find({"owner_sub": user["sub"]}).sort("created_at", -1).limit(50)
    documents = await cursor.to_list(length=50)
    return [to_note(document) for document in documents]


@router.post("", response_model=Note, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreate,
    user: CurrentUser,
    collection: NotesCollection,
) -> Note:
    document = {
        "owner_sub": user["sub"],
        "title": payload.title.strip(),
        "content": payload.content.strip(),
        "created_at": datetime.now(UTC),
    }
    result = await collection.insert_one(document)
    document["_id"] = result.inserted_id
    return to_note(document)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: str,
    user: CurrentUser,
    collection: NotesCollection,
) -> Response:
    if not ObjectId.is_valid(note_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")

    result = await collection.delete_one({"_id": ObjectId(note_id), "owner_sub": user["sub"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
