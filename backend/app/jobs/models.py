"""Immutable records for persistent report-generation jobs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


JobStatus = Literal["queued", "running", "completed", "failed"]
JobStage = Literal[
    "queued",
    "parsing",
    "chunking",
    "extracting",
    "researching",
    "synthesizing",
    "reviewing",
    "composing",
    "rendering",
    "completed",
    "failed",
]


class ReportJobRecord(BaseModel):
    """One durable background-generation state machine."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    job_id: UUID
    report_id: UUID
    status: JobStatus
    stage: JobStage
    progress: int = Field(ge=0, le=100)
    message: str = Field(min_length=1)
    source_paths: tuple[str, ...] = Field(min_length=1, max_length=5)
    source_filenames: tuple[str, ...] = Field(min_length=1, max_length=5)
    settings_json: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    provider: str | None = None
    fallback: bool | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "ReportJobRecord":
        if len(self.source_paths) != len(self.source_filenames):
            raise ValueError("Job source paths and filenames must align.")
        if self.status == "completed":
            if self.stage != "completed" or self.progress != 100:
                raise ValueError("Completed jobs must report 100% completion.")
            if self.completed_at is None:
                raise ValueError("Completed jobs require a completion timestamp.")
        if self.status == "failed":
            if self.stage != "failed" or not self.error_code or not self.error_message:
                raise ValueError("Failed jobs require a safe error code and message.")
            if self.completed_at is None:
                raise ValueError("Failed jobs require a completion timestamp.")
        if self.status in {"queued", "running"} and self.completed_at is not None:
            raise ValueError("Active jobs cannot have a completion timestamp.")
        return self
