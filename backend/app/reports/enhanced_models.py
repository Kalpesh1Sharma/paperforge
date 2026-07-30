"""Strict, immutable models for AI-generated report enhancements."""

import re
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

_NORMALIZED_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


class SynthesisSourceEvidence(BaseModel):
    """Immutable source evidence retained when synthesis falls back locally."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
    )

    chunk_id: UUID
    confidence: StrictFloat = Field(..., ge=0.0, le=1.0)
    references: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_strict_confidence(cls, value: object) -> object:
        """Require an actual float rather than a coercible numeric value."""
        if isinstance(value, bool) or not isinstance(value, float):
            raise ValueError("Synthesis source evidence confidence must be a float.")
        return value


class SynthesisMetadata(BaseModel):
    """Operational metadata recorded for an enhanced or fallback report."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
    )

    provider: str = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)
    elapsed_ms: StrictFloat = Field(..., ge=0.0)
    successful: bool
    fallback: bool = False
    enhanced: bool = True
    reason: str | None = None
    source_evidence: tuple[SynthesisSourceEvidence, ...] = Field(
        default_factory=tuple
    )

    @field_validator("provider")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        """Reject whitespace-only operational labels without coercion."""
        if not value.strip():
            raise ValueError("Synthesis metadata text must not be blank.")
        return value

    @field_validator("model", "reason")
    @classmethod
    def validate_optional_non_blank_text(cls, value: str | None) -> str | None:
        """Reject whitespace-only optional metadata labels without coercion."""
        if value is not None and not value.strip():
            raise ValueError("Synthesis metadata text must not be blank.")
        return value

    @model_validator(mode="after")
    def validate_fallback_state(self) -> "SynthesisMetadata":
        """Require complete, unambiguous metadata for deterministic fallback."""
        if self.provider == "fallback" and not self.fallback:
            raise ValueError(
                "Fallback provider metadata must set fallback to true."
            )
        if not self.fallback:
            return self

        if self.provider != "fallback":
            raise ValueError(
                "Fallback synthesis metadata must use provider='fallback'."
            )
        if self.model is not None:
            raise ValueError("Fallback synthesis metadata must not include a model.")
        if not self.successful:
            raise ValueError("Fallback synthesis metadata must be successful.")
        if self.enhanced:
            raise ValueError("Fallback synthesis metadata must not be AI enhanced.")
        if self.reason is None or not _NORMALIZED_REASON_PATTERN.fullmatch(
            self.reason
        ):
            raise ValueError(
                "Fallback synthesis metadata requires a normalized reason."
            )
        if not self.source_evidence:
            raise ValueError(
                "Fallback synthesis metadata requires source evidence."
            )
        return self


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
