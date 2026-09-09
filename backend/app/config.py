from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables when present."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PaperForge"
    app_version: str = "0.12.0"
    upload_dir: Path = Path(__file__).resolve().parent.parent / "uploads"
    report_storage_dir: Path = Path(__file__).resolve().parent.parent / "reports"
    max_upload_size_bytes: int = 50 * 1024 * 1024
    ai_provider: str = "groq"
    ai_provider_order: str | None = None
    ai_max_retries: int = 2
    ai_retry_base_seconds: float = 1.0
    ai_timeout_seconds: float = 60.0
    groq_api_key: str | None = None
    groq_model: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    mistral_api_key: str | None = None
    mistral_model: str = "mistral-small-latest"
    mistral_base_url: str = "https://api.mistral.ai/v1"
    openai_compatible_api_key: str | None = None
    openai_compatible_model: str | None = None
    openai_compatible_base_url: str | None = None
    superdocs_api_key: str | None = None
    superdocs_api_base_url: str = "https://api.superdocs.app"
    superdocs_poll_interval_seconds: float = 2.0
    superdocs_max_wait_seconds: float = 120.0
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    log_level: str = "INFO"


settings = Settings()
