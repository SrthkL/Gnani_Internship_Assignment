from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# Locate the backend directory using this file's location.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    APP_ENV: str = "development"
    DATABASE_URL: str
    STORAGE_DIR: str = str(BACKEND_DIR / "storage")
    AUDIO_CHUNK_SECONDS: int = 240
    GNANI_API_KEY: str = ""
    GNANI_BASE_URL: str = "https://api.vachana.ai"
    GNANI_LANGUAGE: str = "en-IN"
    GNANI_POLL_SECONDS: int = 10
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_MODEL: str = "llama3.2:3b"
    LLM_API_KEY: SecretStr = SecretStr("")
    LLM_TIMEOUT_SECONDS: int = 180
    APP_URL: str = "http://localhost:3000"
    AUTH_SECRET: SecretStr = SecretStr("")
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: SecretStr = SecretStr("")
    SESSION_HOURS: int = 24
    GUEST_RESULT_MINUTES: int = 60

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
