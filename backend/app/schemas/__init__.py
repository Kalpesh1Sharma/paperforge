"""HTTP request and response schemas for the PaperForge API."""

from app.schemas.responses import (
    ApiError,
    ApiErrorResponse,
    HealthResponse,
    MultiReportCreatedResponse,
    ReportCreatedResponse,
    ReportEditingStateResponse,
    ReportJobResponse,
    ReportMetadataResponse,
    ReviewStateResponse,
)
from app.schemas.requests import (
    ApproveOutlineRequest,
    CreateProjectRequest,
    EditReportSectionRequest,
    RenameProjectRequest,
    ReviewDecisionRequest,
    SetReportSectionLockRequest,
    SwitchReportTemplateRequest,
    TransformReportSectionRequest,
)

__all__ = [
    "ApiError",
    "ApproveOutlineRequest",
    "ApiErrorResponse",
    "HealthResponse",
    "CreateProjectRequest",
    "EditReportSectionRequest",
    "MultiReportCreatedResponse",
    "ReportCreatedResponse",
    "ReportEditingStateResponse",
    "ReportJobResponse",
    "ReportMetadataResponse",
    "RenameProjectRequest",
    "ReviewDecisionRequest",
    "ReviewStateResponse",
    "SetReportSectionLockRequest",
    "SwitchReportTemplateRequest",
    "TransformReportSectionRequest",
]
