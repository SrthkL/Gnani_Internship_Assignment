from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# Locate the backend directory using this file's location.
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    DATABASE_URL: str
    STORAGE_DIR: str = str(BACKEND_DIR / "storage")
    AUDIO_CHUNK_SECONDS: int = 240

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()