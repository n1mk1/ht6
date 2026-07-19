from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PRAXIS_", env_file=".env", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "praxis"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    device_key: str = ""
    environment: str = "development"

    freesolo_mode: str = "http"
    freesolo_endpoint: str = "https://clado-ai--freesolo-lora-serving.modal.run/v1/chat/completions"
    freesolo_model: str = ""
    freesolo_api_key: str = ""
    freesolo_timeout_seconds: float = 20.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("freesolo_mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        if value not in {"http", "disabled", "mock"}:
            raise ValueError("must be one of: http, disabled, mock")
        return value

    @model_validator(mode="after")
    def block_production_mock(self) -> Settings:
        if self.environment.lower() == "production" and self.freesolo_mode == "mock":
            raise ValueError("FreeSOLO mock mode is development-only")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
