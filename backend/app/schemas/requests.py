"""Request-schema markers for the synchronous PaperForge HTTP API.

Multipart uploads are described directly on route parameters because FastAPI
owns their request-body parsing. This module intentionally remains available
for future JSON request contracts without coupling routes to domain models.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.reports.generation_settings import ReportSectionConfiguration, VisualTemplate


ReportOutputFormat = Literal["all", "json", "html", "markdown", "pdf", "docx"]


class ReviewDecisionRequest(BaseModel):
    """One explicit human decision for exactly one currently pending change."""

    model_config = ConfigDict(extra="forbid", strict=True)

    change_id: str = Field(min_length=1)
    feedback: str | None = Field(default=None, min_length=1)


class CreateProjectRequest(BaseModel):
    """Create one empty project ready for the new-report wizard."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=100)


class RenameProjectRequest(BaseModel):
    """Rename exactly one existing project."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=100)


class ApproveOutlineRequest(BaseModel):
    """The exact ordered section list a user has reviewed."""

    model_config = ConfigDict(extra="forbid")

    sections: tuple[ReportSectionConfiguration, ...] = Field(min_length=1)


class EditReportSectionRequest(BaseModel):
    """Replace one generated section with user-controlled prose."""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=30000)


class TransformReportSectionRequest(BaseModel):
    """Request one bounded AI-assisted section transformation."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["rewrite", "shorten", "expand"]


class SetReportSectionLockRequest(BaseModel):
    """Lock or unlock one approved section."""

    model_config = ConfigDict(extra="forbid")
    locked: bool


class SwitchReportTemplateRequest(BaseModel):
    """Choose a visual template without changing report content."""

    model_config = ConfigDict(extra="forbid")
    template: VisualTemplate
