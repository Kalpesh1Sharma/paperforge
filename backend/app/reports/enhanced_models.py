"""Strict, immutable models for AI-generated report enhancements."""

from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    field_validator,
    model_validator,
)

from app.reports.models import Finding, ResearchReport


class SynthesisMetadata(BaseModel):
    """Operational metadata recorded for a successful document synthesis."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
    )

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    elapsed_ms: StrictFloat = Field(..., ge=0.0)
    successful: bool

    @field_validator("provider", "model")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        """Reject whitespace-only operational labels without coercion."""
        if not value.strip():
            raise ValueError("Synthesis metadata text must not be blank.")
        return value


class SynthesizedSection(BaseModel):
    """An AI-generated report section with verified source provenance."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    heading: str
    content: str
    supporting_chunk_ids: tuple[UUID, ...] = Field(..., min_length=1)

    @field_validator("heading", "content")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        """Reject whitespace-only generated section text without coercion."""
        if not value.strip():
            raise ValueError("Synthesized section text must not be blank.")
        return value


class EnhancedResearchReport(BaseModel):
    """Immutable AI enhancement overlay for a deterministic research report."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    base_report: ResearchReport
    executive_summary: str = Field(min_length=1)
    findings: tuple[Finding, ...] = Field(default_factory=tuple)
    sections: tuple[SynthesizedSection, ...] = Field(default_factory=tuple)
    synthesis_metadata: SynthesisMetadata

    @model_validator(mode="after")
    def validate_enhancement_content(self) -> "EnhancedResearchReport":
        """Require non-blank generated content with finding provenance."""
        if not self.executive_summary.strip():
            raise ValueError("Enhanced executive_summary must not be blank.")

        for finding in self.findings:
            if not finding.supporting_chunk_ids:
                raise ValueError(
                    "EnhancedResearchReport findings require source provenance."
                )
            if not finding.title.strip() or not finding.description.strip():
                raise ValueError("EnhancedResearchReport findings must not be blank.")

        return self
