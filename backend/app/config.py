from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables when present."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PaperForge"
    app_version: str = "0.1.0"
    upload_dir: Path = Path(__file__).resolve().parent.parent / "uploads"
    max_upload_size_bytes: int = 50 * 1024 * 1024


settings = Settings()
