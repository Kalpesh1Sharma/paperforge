"""Unified model returned by all document parsers."""

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

FileType: TypeAlias = Literal["pdf", "docx", "md", "txt"]
MetadataValue: TypeAlias = str | int | float | bool | None


class ParsedPageSpan(BaseModel):
    """One PDF page's one-based number and location in normalized text."""

    model_config = ConfigDict(extra="forbid", strict=True)

    page_number: int = Field(ge=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_span(self) -> "ParsedPageSpan":
        if self.end_char < self.start_char:
            raise ValueError("Page span end must not precede its start.")
        return self


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
    pages: tuple[ParsedPageSpan, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_pages(self) -> "ParsedDocument":
        if not self.pages:
            return self
        if self.file_type != "pdf":
            raise ValueError("Only PDF documents may contain page spans.")
        if self.page_count != len(self.pages):
            raise ValueError("PDF page span count must match page_count.")
        previous_end = 0
        for expected_number, page in enumerate(self.pages, start=1):
            if page.page_number != expected_number:
                raise ValueError("PDF page spans must use consecutive one-based numbers.")
            if page.start_char < previous_end or page.end_char > self.character_count:
                raise ValueError("PDF page spans must be ordered within extracted_text.")
            previous_end = page.end_char
        return self
