"""HTTP request and response schemas for the PaperForge API."""

from app.schemas.responses import (
    ApiError,
    ApiErrorResponse,
    HealthResponse,
    MultiReportCreatedResponse,
    ReportCreatedResponse,
    ReportJobResponse,
    ReportMetadataResponse,
    ReviewStateResponse,
)
from app.schemas.requests import (
    CreateProjectRequest,
    RenameProjectRequest,
    ReviewDecisionRequest,
)

__all__ = [
    "ApiError",
    "ApiErrorResponse",
    "HealthResponse",
    "CreateProjectRequest",
    "MultiReportCreatedResponse",
    "ReportCreatedResponse",
    "ReportJobResponse",
    "ReportMetadataResponse",
    "RenameProjectRequest",
    "ReviewDecisionRequest",
    "ReviewStateResponse",
]
