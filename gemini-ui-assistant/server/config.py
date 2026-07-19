from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    assistant_port: int = 8002
    cors_origins: str = "http://localhost:5173,http://localhost:5174"

    # Request handling limits
    gemini_timeout_s: float = 15.0
    max_output_tokens: int = 512
    max_answer_chars: int = 2000
    rate_limit_requests: int = 10
    rate_limit_window_s: float = 60.0

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8")

    @property
    def mock_mode(self) -> bool:
        return not self.gemini_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
