"""Validated user choices collected by the new-report wizard."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.reports.presentation_models import ReportMode


VisualTemplate = Literal[
    "paperforge-classic",
    "modern-research",
    "editorial",
    "minimal",
]


class ReportGenerationSettings(BaseModel):
    """One complete, render-safe set of report wizard selections."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    project_title: str = Field(min_length=1, max_length=100)
    research_domain: str = Field(min_length=1, max_length=100)
    purpose: str | None = Field(default=None, max_length=500)
    structure: ReportMode = ReportMode.PROFESSIONAL
    visual_template: VisualTemplate = "paperforge-classic"
    report_title: str = Field(min_length=1, max_length=180)
    author: str = Field(min_length=1, max_length=100)
    organisation: str | None = Field(default=None, max_length=120)

    @field_validator("project_title", "research_domain", "report_title", "author")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Required report settings must not be blank.")
        return normalized

    @field_validator("purpose", "organisation")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split()) or None
