from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunIngest(BaseModel):
    """A tracing run posted by the QNX device. `username` identifies the
    participant; every other field the device sends (scores, metrics, quality,
    trace, timing, ...) is accepted and stored as-is."""

    model_config = ConfigDict(extra="allow")

    username: str = Field(min_length=1, max_length=120)
    session_id: str | None = None
    device_id: str | None = None
    scores: dict[str, Any] | None = None


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
