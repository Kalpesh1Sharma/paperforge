"""Structured output returned by document chunking strategies."""

from typing import TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.parsed_document import MetadataValue

ChunkMetadataValue: TypeAlias = (
    str | int | float | bool | None | dict[str, MetadataValue]
)


class DocumentChunk(BaseModel):
    """A deterministic, source-addressable segment of a parsed document."""

    model_config = ConfigDict(extra="forbid", strict=True)

    chunk_id: UUID
    document_filename: str = Field(..., min_length=1)
    chunk_index: int = Field(..., ge=0)
    text: str = Field(..., min_length=1)
    start_char: int = Field(..., ge=0)
    end_char: int = Field(..., gt=0)
    word_count: int = Field(..., ge=0)
    character_count: int = Field(..., ge=0)
    metadata: dict[str, ChunkMetadataValue] = Field(default_factory=dict)
