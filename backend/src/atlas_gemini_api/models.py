from datetime import datetime

from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(default="", max_length=2_000)


class Note(BaseModel):
    id: str
    title: str
    content: str
    created_at: datetime


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4_000)
    temperature: float = Field(default=0.4, ge=0, le=2)


class GenerateResponse(BaseModel):
    text: str
    model: str
