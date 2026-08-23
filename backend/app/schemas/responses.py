"""Stable OpenAPI response contracts for the PaperForge HTTP API."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiError(BaseModel):
    """One sanitized API error suitable for clients and logs."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., examples=["invalid_document"])
    message: str = Field(..., examples=["The uploaded file is not a valid PDF."])
    request_id: str = Field(..., examples=["9e4a4d14f3d14f83a151bb17c0a37fe8"])


class ApiErrorResponse(BaseModel):
    """Envelope returned for all expected request failures."""

    model_config = ConfigDict(extra="forbid")

    error: ApiError


class HealthResponse(BaseModel):
    """Readiness information for orchestration and load balancers."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy"] = "healthy"
    service: str = "PaperForge"
    version: str
    ready: Literal[True] = True


class ReportDocumentMetadata(BaseModel):
    """Stored source-document facts without report body content."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    file_type: str
    page_count: int | None
    word_count: int = Field(ge=0)
    character_count: int = Field(ge=0)


class ReportGenerationMetadata(BaseModel):
    """Safe operational metadata for a completed report."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["completed"] = "completed"
    provider: str
    model: str | None = None
    elapsed_ms: float = Field(ge=0)
    successful: bool
    fallback: bool
    enhanced: bool
    reason: str | None = None


class ReportCreatedResponse(BaseModel):
    """Response emitted once all requested local report artifacts exist."""

    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    status: Literal["completed"] = "completed"
    available_formats: tuple[Literal["json", "html", "markdown", "pdf"], ...]
    metadata: ReportDocumentMetadata


class MultiReportCreatedResponse(BaseModel):
    """Response emitted once a multi-source report has all local artifacts."""

    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    status: Literal["completed"] = "completed"
    available_formats: tuple[Literal["json", "html", "markdown", "pdf"], ...]
    documents: tuple[ReportDocumentMetadata, ...] = Field(min_length=2, max_length=5)


class ReportMetadataResponse(BaseModel):
    """Metadata endpoint contract, deliberately excluding report content."""

    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    status: Literal["completed"] = "completed"
    available_formats: tuple[Literal["json", "html", "markdown", "pdf"], ...]
    document: ReportDocumentMetadata | None = None
    documents: tuple[ReportDocumentMetadata, ...] | None = None
    generation: ReportGenerationMetadata

    @model_validator(mode="after")
    def validate_source_shape(self) -> "ReportMetadataResponse":
        if (self.document is None) == (self.documents is None):
            raise ValueError("Metadata must contain exactly one source shape.")
        return self


class ReviewChangeResponse(BaseModel):
    """Exact before/after provider proposal displayed to a human reviewer."""

    model_config = ConfigDict(extra="forbid")

    change_id: str
    operation: Literal["edit", "create", "delete"]
    chunk_id: str | None = None
    document_id: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    ai_explanation: str | None = None
    insert_after_chunk_id: str | None = None
    insert_before_chunk_id: str | None = None


class ReviewStateResponse(BaseModel):
    """Safe local state for a controlled document review."""

    model_config = ConfigDict(extra="forbid")

    report_id: UUID
    status: Literal["awaiting_approval", "processing", "completed", "failed", "cancelled", "needs_attention"]
    pending_changes: tuple[ReviewChangeResponse, ...] = ()
    approved_changes: tuple[ReviewChangeResponse, ...] = ()
    rejected_changes: tuple[ReviewChangeResponse, ...] = ()
    final_docx_available: bool
