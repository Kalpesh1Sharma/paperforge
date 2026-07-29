"""Strict, immutable models for deterministic research reports."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Finding(BaseModel):
    """A report finding with provenance to its source document chunks."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    title: str
    description: str
    supporting_chunk_ids: tuple[UUID, ...]


class TimelineEvent(BaseModel):
    """A date-bearing report event with provenance to source chunks."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    date: str
    description: str
    supporting_chunk_ids: tuple[UUID, ...]


class ReportSection(BaseModel):
    """An optional, manually supplied section of a research report."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    heading: str
    content: str


class ResearchReport(BaseModel):
    """An immutable, deterministic report synthesized from knowledge objects."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    title: str
    executive_summary: str
    findings: tuple[Finding, ...] = Field(default_factory=tuple)
    important_entities: tuple[str, ...] = Field(default_factory=tuple)
    important_definitions: tuple[str, ...] = Field(default_factory=tuple)
    important_metrics: tuple[str, ...] = Field(default_factory=tuple)
    timeline: tuple[TimelineEvent, ...] = Field(default_factory=tuple)
    references: tuple[str, ...] = Field(default_factory=tuple)
    sections: tuple[ReportSection, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_unique_collections(self) -> "ResearchReport":
        """Reject duplicate report-wide entities and references exactly."""
        if len(set(self.important_entities)) != len(self.important_entities):
            raise ValueError("important_entities must not contain duplicate values.")

        if len(set(self.references)) != len(self.references):
            raise ValueError("references must not contain duplicate values.")

        return self
