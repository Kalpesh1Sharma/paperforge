from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables when present."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PaperForge"
    app_version: str = "0.11.0"
    upload_dir: Path = Path(__file__).resolve().parent.parent / "uploads"
    report_storage_dir: Path = Path(__file__).resolve().parent.parent / "reports"
    max_upload_size_bytes: int = 50 * 1024 * 1024
    groq_api_key: str | None = None
    groq_model: str | None = None
    superdocs_api_key: str | None = None
    superdocs_api_base_url: str = "https://api.superdocs.app"
    superdocs_poll_interval_seconds: float = 2.0
    superdocs_max_wait_seconds: float = 120.0
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"


settings = Settings()
