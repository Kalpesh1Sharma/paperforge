"""Unified model returned by all document parsers."""

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

FileType: TypeAlias = Literal["pdf", "docx", "md", "txt"]
MetadataValue: TypeAlias = str | int | float | bool | None


class ParsedDocument(BaseModel):
    """The normalized result of extracting text from a supported document."""

    model_config = ConfigDict(extra="forbid", strict=True)

    filename: str = Field(..., min_length=1)
    file_type: FileType
    extracted_text: str = Field(..., min_length=1)
    page_count: int | None = Field(default=None, ge=0)
    word_count: int = Field(..., ge=0)
    character_count: int = Field(..., ge=0)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)
