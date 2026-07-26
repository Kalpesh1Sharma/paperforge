from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "PaperForge"
    APP_VERSION: str = "0.1.0"


settings = Settings()