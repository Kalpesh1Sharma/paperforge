"""Strict schema for Groq knowledge extraction responses."""

from pydantic import BaseModel, ConfigDict, Field, StrictFloat


class KnowledgeResponse(BaseModel):
    """Provider response fields before assigning the source chunk UUID."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
    )

    entities: tuple[str, ...] = Field(...)
    facts: tuple[str, ...] = Field(...)
    definitions: tuple[str, ...] = Field(...)
    metrics: tuple[str, ...] = Field(...)
    dates: tuple[str, ...] = Field(...)
    references: tuple[str, ...] = Field(...)
    confidence: StrictFloat = Field(..., ge=0.0, le=1.0)
