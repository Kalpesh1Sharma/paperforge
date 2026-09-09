"""Immutable project and source records shared by storage and HTTP layers."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProjectSource(BaseModel):
    """One ordered source associated with a project report."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    filename: str = Field(min_length=1)
    file_type: str = Field(min_length=1)
    page_count: int | None = Field(default=None, ge=0)
    word_count: int = Field(ge=0)
    character_count: int = Field(ge=0)


class ProjectRecord(BaseModel):
    """One durable workspace project, optionally linked to a completed report."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: UUID
    title: str = Field(min_length=1, max_length=100)
    report_id: UUID | None = None
    status: Literal["draft", "ready"]
    sources: tuple[ProjectSource, ...] = ()
    available_formats: tuple[str, ...] = ()
    created_at: datetime
    updated_at: datetime
