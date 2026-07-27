import logging

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.upload import router as upload_router
from app.config import settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)

app.include_router(health_router)
app.include_router(upload_router)
