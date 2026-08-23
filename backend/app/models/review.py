"""Strict immutable records for the persisted human-review workflow."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PendingChange(BaseModel):
    """One exact provider-proposed document change for human review."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    change_id: str = Field(min_length=1)
    operation: Literal["edit", "create", "delete"]
    chunk_id: str | None = None
    document_id: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    ai_explanation: str | None = None
    insert_after_chunk_id: str | None = None
    insert_before_chunk_id: str | None = None

    @field_validator(
        "change_id", "chunk_id", "document_id", "old_html", "new_html", "ai_explanation", "insert_after_chunk_id", "insert_before_chunk_id"
    )
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Review change text must not be blank.")
        return value


class ReviewState(BaseModel):
    """Small local record; it intentionally excludes provider payloads and secrets."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: Literal[1] = 1
    report_id: UUID
    session_id: str = Field(min_length=1)
    job_id: str | None = None
    status: Literal[
        "awaiting_approval", "processing", "completed", "failed", "cancelled", "needs_attention"
    ]
    pending_changes: tuple[PendingChange, ...] = ()
    approved_changes: tuple[PendingChange, ...] = ()
    rejected_changes: tuple[PendingChange, ...] = ()
    final_docx_available: bool = False
