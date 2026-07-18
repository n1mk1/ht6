from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "LaunchKit API"
    app_env: str = "development"
    frontend_origins: str = "http://localhost:3000"

    mongodb_uri: str | None = None
    mongodb_database: str = "launchkit"

    auth0_domain: str | None = None
    auth0_audience: str | None = None

    # optional shared key the QNX device must send (X-Device-Key) to POST runs
    device_ingest_key: str | None = None

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash"

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def auth0_configured(self) -> bool:
        return bool(self.auth0_domain and self.auth0_audience)

    @property
    def mongodb_configured(self) -> bool:
        return bool(self.mongodb_uri)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
