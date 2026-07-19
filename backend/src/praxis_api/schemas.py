from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OpenObject(BaseModel):
    model_config = ConfigDict(extra="allow")


class TaskPayload(OpenObject):
    type: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    difficulty: str | int | float | None = None
    hand: str | None = None


class TimingPayload(OpenObject):
    started_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class ScoresPayload(OpenObject):
    accuracy: float | None = Field(default=None, ge=0, le=100)
    stability: float | None = Field(default=None, ge=0, le=100)
    accuracy_band: str | None = None
    stability_band: str | None = None
    version: str | None = None


class MetricsPayload(OpenObject):
    accuracy_score: float | None = Field(default=None, ge=0, le=100)
    stability_score: float | None = Field(default=None, ge=0, le=100)
    coverage_pct: float | None = Field(default=None, ge=0, le=100)
    completion_time_seconds: float | None = Field(default=None, ge=0)
    mean_dev_mm: float | None = Field(default=None, ge=0)
    max_dev_mm: float | None = Field(default=None, ge=0)
    rms_dev_mm: float | None = Field(default=None, ge=0)
    tremor_rms_deg_s: float | None = Field(default=None, ge=0)
    gyro_rms_deg_s: float | None = Field(default=None, ge=0)
    peak_angular_velocity_deg_s: float | None = Field(default=None, ge=0)


class QualityPayload(OpenObject):
    calibration_valid: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class TracePayload(OpenObject):
    frame: list[int] | None = None
    reference: list[list[float]] = Field(default_factory=list)
    red: list[list[float]] = Field(default_factory=list)


class QnxSessionPayload(OpenObject):
    schema_version: str
    username: str = Field(min_length=1, max_length=120)
    session_id: str = Field(min_length=1, max_length=160)
    device_id: str = Field(min_length=1, max_length=160)
    task: TaskPayload
    created_at: datetime
    timing: TimingPayload
    scores: ScoresPayload
    metrics: MetricsPayload
    quality: QualityPayload
    trace: TracePayload
    score_definitions: dict[str, Any] | None = None
    percentiles: dict[str, Any] | None = None
    explanation: dict[str, Any] | None = None
    artifacts: dict[str, Any] | None = None

    @field_validator("schema_version")
    @classmethod
    def supported_schema(cls, value: str) -> str:
        if value != "3.0":
            raise ValueError("unsupported QNX schema version; expected 3.0")
        return value

    @field_validator("username", "session_id", "device_id")
    @classmethod
    def trim_identifiers(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)


class UserResolve(BaseModel):
    username: str = Field(min_length=1, max_length=120)

    @field_validator("username")
    @classmethod
    def trim_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value
