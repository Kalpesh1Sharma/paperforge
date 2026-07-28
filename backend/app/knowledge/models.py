"""Strict, immutable models for deterministic knowledge extraction."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat


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
