"""Strict public models for editable report outlines."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.reports.generation_settings import ReportSectionConfiguration
from app.reports.presentation_models import PresentationSectionKey

OutlineProposalStatus = Literal["draft", "approved"]
EvidenceLevel = Literal["strong", "moderate", "limited"]


class _OutlineModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceAvailability(_OutlineModel):
    key: PresentationSectionKey
    heading: str
    level: EvidenceLevel
    evidence_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    reason: str


class OutlineSection(ReportSectionConfiguration):
    evidence: EvidenceAvailability


class OutlineProposal(_OutlineModel):
    proposal_id: UUID
    status: OutlineProposalStatus
    revision: int = Field(ge=1)
    source_filenames: tuple[str, ...] = Field(min_length=1, max_length=5)
    sections: tuple[OutlineSection, ...] = Field(min_length=1)
    catalog: tuple[EvidenceAvailability, ...] = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None = None
