"""Strict, immutable models for deterministic knowledge extraction."""

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


_NORMALIZED_REASON_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


class KnowledgeExtractionMetadata(BaseModel):
    """Immutable operational context for a successful knowledge extraction."""

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
    reason: str | None = None

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        """Reject whitespace-only provider labels without coercing them."""
        if not value.strip():
            raise ValueError(
                "Knowledge extraction metadata provider must not be blank."
            )
        return value

    @field_validator("model", "reason")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        """Reject whitespace-only optional operational labels."""
        if value is not None and not value.strip():
            raise ValueError("Knowledge extraction metadata text must not be blank.")
        return value

    @model_validator(mode="after")
    def validate_successful_extraction(self) -> "KnowledgeExtractionMetadata":
        """Require unambiguous metadata for primary and fallback results."""
        if not self.successful:
            raise ValueError(
                "Knowledge extraction metadata for a returned result must be "
                "successful."
            )

        if not self.fallback:
            if self.provider == "deterministic":
                raise ValueError(
                    "Deterministic knowledge metadata must be marked as fallback."
                )
            if self.reason is not None:
                raise ValueError(
                    "Primary knowledge metadata must not include a fallback reason."
                )
            return self

        if self.provider != "deterministic":
            raise ValueError(
                "Fallback knowledge metadata must use provider='deterministic'."
            )
        if self.model is not None:
            raise ValueError("Fallback knowledge metadata must not include a model.")
        if self.reason is None or not _NORMALIZED_REASON_PATTERN.fullmatch(
            self.reason
        ):
            raise ValueError(
                "Fallback knowledge metadata requires a normalized reason."
            )
        return self


class KnowledgeObject(BaseModel):
    """Knowledge extracted from one document chunk without interpretation."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
    )

    chunk_id: UUID
    entities: tuple[str, ...] = Field(default_factory=tuple)
    facts: tuple[str, ...] = Field(default_factory=tuple)
    definitions: tuple[str, ...] = Field(default_factory=tuple)
    metrics: tuple[str, ...] = Field(default_factory=tuple)
    dates: tuple[str, ...] = Field(default_factory=tuple)
    references: tuple[str, ...] = Field(default_factory=tuple)
    confidence: StrictFloat = Field(..., ge=0.0, le=1.0)
    extraction_metadata: KnowledgeExtractionMetadata | None = Field(
        default=None,
        exclude=True,
    )
