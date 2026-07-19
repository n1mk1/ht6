"""Models for review items and the copilot API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Priority = Literal["needs_attention", "review", "routine"]
QualityVerdict = Literal["unusable", "usable_with_warnings", "clean"]
ReviewStatus = Literal["pending", "approved", "edited"]

MAX_NOTE_CHARS = 2000


class MetricDelta(BaseModel):
    label: str
    current: float
    participant_avg: float
    delta: float


class ReviewItem(BaseModel):
    id: str
    run_id: str
    participant_id: str  # anonymous: P-1, P-2, ...
    received_at: str = ""
    priority: Priority
    quality_verdict: QualityVerdict
    quality_reasons: list[str] = Field(default_factory=list)
    deltas: list[MetricDelta] = Field(default_factory=list)
    sessions_compared: int = 0
    draft_note: str = ""
    note_is_mock: bool = False
    decision_log: list[str] = Field(default_factory=list)
    status: ReviewStatus = "pending"


class EditNoteRequest(BaseModel):
    note: str = Field(min_length=1, max_length=MAX_NOTE_CHARS)


class IngestRun(BaseModel):
    """A session pushed directly to the copilot (demo/local mode).

    Mirrors the Praxis API session document; unknown fields are ignored.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    session_id: str = ""
    device_id: str = ""
    username: str = ""
    user: dict = Field(default_factory=dict)  # v1 API nests {username, ...}
    received_at: str = ""
    created_at: str = ""
    scores: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)
    quality: dict = Field(default_factory=dict)
    timing: dict = Field(default_factory=dict)
