"""Health and readiness endpoint for PaperForge deployments."""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_settings
from app.config import Settings
from app.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check service health and readiness",
)
def health(active_settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Return a deterministic readiness result without testing external providers."""
    return HealthResponse(version=active_settings.app_version)
