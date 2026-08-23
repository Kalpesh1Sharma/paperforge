from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables when present."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PaperForge"
    app_version: str = "0.9.1"
    upload_dir: Path = Path(__file__).resolve().parent.parent / "uploads"
    report_storage_dir: Path = Path(__file__).resolve().parent.parent / "reports"
    max_upload_size_bytes: int = 50 * 1024 * 1024
    groq_api_key: str | None = None
    groq_model: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"


settings = Settings()
