from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_FOLDER = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    copilot_port: int = 8003
    backend_url: str = "http://localhost:8000"
    poll_interval_s: float = 5.0
    cors_origins: str = "http://localhost:5173,http://localhost:5174"

    gemini_timeout_s: float = 15.0
    max_output_tokens: int = 400
    history_window: int = 5  # sessions used for the participant's average
    review_delta_threshold: float = 15.0  # score-point change that flags "review"
    min_imu_samples: int = 50

    store_path: Path = _FOLDER / "data" / "reviews.json"

    model_config = SettingsConfigDict(
        env_file=_FOLDER / ".env", env_file_encoding="utf-8"
    )

    @property
    def mock_mode(self) -> bool:
        return not self.gemini_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
