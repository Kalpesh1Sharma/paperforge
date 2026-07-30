"""Strict immutable models for deterministic report presentation.

These models are deliberately separate from the canonical report models.  They
contain only materialized, render-ready views derived by ``ReportComposer`` and
retain source UUIDs solely for provenance-aware downstream consumers.
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, field_validator, model_validator


PresentationSectionKey = Literal[
    "abstract",
    "document-overview",
    "research-methodology",
    "executive-summary",
    "key-insights",
    "technical-analysis",
    "historical-timeline",
    "important-concepts",
    "evidence-summary",
    "appendix",
]

PresentationStatus = Literal[
    "AI-enhanced",
    "Deterministic fallback",
    "Deterministic report",
]

ImportanceLabel = Literal["HIGH", "MEDIUM", "LOW"]


class ReportMode(str, Enum):
    """Named deterministic presentation policies for composed reports."""

    PROFESSIONAL = "professional"
    EXECUTIVE = "executive"
    TECHNICAL = "technical"
    FULL = "full"


PRESENTATION_SECTION_SPECS: tuple[
    tuple[PresentationSectionKey, str, str], ...
] = (
    ("abstract", "Abstract", "abstract"),
    ("document-overview", "Document Overview", "document-overview"),
    ("research-methodology", "Report Guide", "research-methodology"),
    ("executive-summary", "Executive Summary", "executive-summary"),
    ("key-insights", "Major Findings", "key-insights"),
    ("technical-analysis", "Technical Analysis", "technical-analysis"),
    ("historical-timeline", "Historical Evolution", "historical-timeline"),
    ("important-concepts", "Key Concepts", "important-concepts"),
    ("evidence-summary", "Evidence Summary", "evidence-summary"),
    ("appendix", "Appendix", "appendix"),
)

_ANCHOR_PATTERN = re.compile(r"[a-z][a-z0-9-]*")


class _PresentationBaseModel(BaseModel):
    """Shared immutable Pydantic configuration for presentation-only values."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
    )


class PresentationBudget(_PresentationBaseModel):
    """Immutable limits that control visibility without changing source data.

    ``None`` means a mode intentionally has no limit for that presentation
    category.  A finite value of ``0`` is valid and suppresses only the
    rendered allocation; the composer retains the eligible material as hidden
    presentation data.
    """

    abstract_word_limit: int | None = Field(default=180, ge=0)
    executive_summary_paragraph_limit: int | None = Field(default=5, ge=0)
    key_insights_limit: int | None = Field(default=8, ge=0)
    technical_analysis_limit: int | None = Field(default=8, ge=0)
    timeline_limit: int | None = Field(default=10, ge=0)
    primary_concepts_limit: int | None = Field(default=6, ge=0)
    entities_per_category_limit: int | None = Field(default=8, ge=0)
    metrics_limit: int | None = Field(default=12, ge=0)
    appendix_findings_limit: int | None = Field(default=15, ge=0)
    appendix_concepts_limit: int | None = Field(default=10, ge=0)
    primary_references_limit: int | None = Field(default=6, ge=0)
    evidence_table_row_limit: int | None = Field(default=10, ge=0)

    @classmethod
    def professional(cls) -> "PresentationBudget":
        """Return the default publication-oriented composition budget."""
        return cls()

    @classmethod
    def executive(cls) -> "PresentationBudget":
        """Return the compact leadership-oriented composition budget."""
        return cls(
            abstract_word_limit=120,
            executive_summary_paragraph_limit=3,
            key_insights_limit=5,
            technical_analysis_limit=3,
            timeline_limit=5,
            primary_concepts_limit=3,
            entities_per_category_limit=5,
            metrics_limit=6,
            appendix_findings_limit=5,
            appendix_concepts_limit=3,
            primary_references_limit=4,
            evidence_table_row_limit=6,
        )

    @classmethod
    def technical(cls) -> "PresentationBudget":
        """Return the detail-oriented engineering composition budget."""
        return cls(
            abstract_word_limit=200,
            executive_summary_paragraph_limit=5,
            key_insights_limit=8,
            technical_analysis_limit=16,
            timeline_limit=12,
            primary_concepts_limit=10,
            entities_per_category_limit=10,
            metrics_limit=18,
            appendix_findings_limit=20,
            appendix_concepts_limit=15,
            primary_references_limit=8,
            evidence_table_row_limit=10,
        )

    @classmethod
    def full(cls) -> "PresentationBudget":
        """Return the uncapped eligible-content composition budget."""
        return cls(
            abstract_word_limit=250,
            executive_summary_paragraph_limit=None,
            key_insights_limit=None,
            technical_analysis_limit=None,
            timeline_limit=None,
            primary_concepts_limit=None,
            entities_per_category_limit=None,
            metrics_limit=None,
            appendix_findings_limit=None,
            appendix_concepts_limit=None,
            primary_references_limit=None,
            evidence_table_row_limit=10,
        )

    @classmethod
    def for_mode(cls, mode: ReportMode) -> "PresentationBudget":
        """Resolve one named budget without embedding limits in the composer."""
        if not isinstance(mode, ReportMode):
            raise ValueError("mode must be a ReportMode instance.")
        presets = {
            ReportMode.PROFESSIONAL: cls.professional,
            ReportMode.EXECUTIVE: cls.executive,
            ReportMode.TECHNICAL: cls.technical,
            ReportMode.FULL: cls.full,
        }
        return presets[mode]()


def _non_blank(value: str, field_name: str) -> str:
    """Reject whitespace-only renderable text without rewriting evidence."""
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank.")
    return value


def _non_blank_unique_text(
    values: tuple[str, ...],
    field_name: str,
) -> tuple[str, ...]:
    """Require immutable, readable, duplicate-free presentation text."""
    if any(not value.strip() for value in values):
        raise ValueError(f"{field_name} must not contain blank text.")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicate values.")
    return values


class DocumentMetadata(_PresentationBaseModel):
    """Deterministic cover-page metadata derived from report and source data."""

    title: str = Field(min_length=1)
    filename: str | None = None
    file_type: str | None = None
    page_count: int | None = Field(default=None, ge=0)
    generated_on: date | None = None
    knowledge_object_count: int = Field(ge=0)
    evidence_source_count: int = Field(ge=0)
    mean_confidence: StrictFloat | None = Field(default=None, ge=0.0, le=1.0)
    status: PresentationStatus
    domain: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = None

    @field_validator("title", "domain")
    @classmethod
    def validate_required_text(cls, value: str, info: object) -> str:
        """Keep cover labels readable and deterministic."""
        return _non_blank(value, getattr(info, "field_name", "Cover value"))

    @field_validator("filename", "file_type", "provider", "model")
    @classmethod
    def validate_optional_text(cls, value: str | None, info: object) -> str | None:
        """Reject blank optional source metadata when it is supplied."""
        if value is not None:
            return _non_blank(value, getattr(info, "field_name", "Source value"))
        return value

    @field_validator("mean_confidence", mode="before")
    @classmethod
    def validate_confidence_type(cls, value: object) -> object:
        """Require genuine floating-point confidence rather than coercion."""
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, float):
            raise ValueError("mean_confidence must be a float.")
        return value


class PresentationEvidence(_PresentationBaseModel):
    """Display labels and retained raw source provenance for one presented item."""

    supporting_chunk_ids: tuple[UUID, ...] = Field(default_factory=tuple)
    source_labels: tuple[str, ...] = Field(default_factory=tuple)
    references: tuple[str, ...] = Field(default_factory=tuple)
    confidence: StrictFloat | None = Field(default=None, ge=0.0, le=1.0)
    confidence_label: str | None = None
    source_count: int = Field(default=0, ge=0)

    @field_validator("supporting_chunk_ids")
    @classmethod
    def validate_source_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Keep raw provenance ordered and unambiguous."""
        if len(set(value)) != len(value):
            raise ValueError("supporting_chunk_ids must not contain duplicate UUIDs.")
        return value

    @field_validator("source_labels", "references")
    @classmethod
    def validate_text_collections(
        cls,
        value: tuple[str, ...],
        info: object,
    ) -> tuple[str, ...]:
        """Reject ambiguous labels or citations before rendering."""
        return _non_blank_unique_text(
            value,
            getattr(info, "field_name", "Evidence collection"),
        )

    @field_validator("confidence_label")
    @classmethod
    def validate_confidence_label(cls, value: str | None) -> str | None:
        """Permit absent display calibration but not blank labels."""
        if value is not None:
            return _non_blank(value, "confidence_label")
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence_type(cls, value: object) -> object:
        """Keep raw confidence strict and finite."""
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, float):
            raise ValueError("Evidence confidence must be a float.")
        return value

    @model_validator(mode="after")
    def validate_evidence_shape(self) -> "PresentationEvidence":
        """Ensure counts and human labels match the retained provenance."""
        if self.source_count != len(self.supporting_chunk_ids):
            raise ValueError("source_count must equal the provenance UUID count.")
        if self.supporting_chunk_ids and len(self.source_labels) != len(
            self.supporting_chunk_ids
        ):
            raise ValueError("source_labels must match the provenance UUID count.")
        return self


class InsightCard(_PresentationBaseModel):
    """A selected source-backed finding for the main presentation."""

    key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    importance: ImportanceLabel | None = None
    evidence: PresentationEvidence

    @field_validator("key", "title", "summary")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        """Reject blank finding presentation text."""
        return _non_blank(value, getattr(info, "field_name", "Insight value"))


class GroupedFinding(_PresentationBaseModel):
    """A transient visual grouping of otherwise authoritative findings."""

    heading: str = Field(min_length=1)
    findings: tuple[InsightCard, ...] = Field(min_length=1)

    @field_validator("heading")
    @classmethod
    def validate_heading(cls, value: str) -> str:
        """Require a readable deterministic grouping label."""
        return _non_blank(value, "Finding group heading")


class ConceptCard(_PresentationBaseModel):
    """A consolidated definition with its display-safe source evidence."""

    key: str = Field(min_length=1)
    concept: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    related_concepts: tuple[str, ...] = Field(default_factory=tuple)
    why_it_matters: str | None = None
    evidence: PresentationEvidence

    @field_validator("key", "concept", "definition")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        """Keep concept card content concise and nonblank."""
        return _non_blank(value, getattr(info, "field_name", "Concept value"))

    @field_validator("related_concepts")
    @classmethod
    def validate_related_concepts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Keep derived relationships deterministic and duplicate-free."""
        return _non_blank_unique_text(value, "related_concepts")

    @field_validator("why_it_matters")
    @classmethod
    def validate_why_it_matters(cls, value: str | None) -> str | None:
        """Allow absent inference when no supporting finding exists."""
        if value is not None:
            return _non_blank(value, "why_it_matters")
        return value


class EntityCard(_PresentationBaseModel):
    """One normalized entity retained for the composed presentation."""

    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    evidence: PresentationEvidence

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Require a readable entity label."""
        return _non_blank(value, "Entity name")

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Retain only deterministic, unique aliases."""
        return _non_blank_unique_text(value, "aliases")


class EntityPresentationGroup(_PresentationBaseModel):
    """Visible entities grouped by the stable intelligence category."""

    category: str = Field(min_length=1)
    entities: tuple[EntityCard, ...] = Field(min_length=1)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        """Require an explicit group label even for legacy entities."""
        return _non_blank(value, "Entity category")


class TimelineCard(_PresentationBaseModel):
    """A historical event with retained evidence for presentation."""

    date: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence: PresentationEvidence

    @field_validator("date", "description")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        """Reject blank timeline content."""
        return _non_blank(value, getattr(info, "field_name", "Timeline value"))


class ReferenceCard(_PresentationBaseModel):
    """A consolidated reference and the evidence sources that cite it."""

    reference: str = Field(min_length=1)
    evidence: PresentationEvidence

    @field_validator("reference")
    @classmethod
    def validate_reference(cls, value: str) -> str:
        """Require nonblank citation content."""
        return _non_blank(value, "Reference")


class MetricCard(_PresentationBaseModel):
    """One source-backed, display-safe labelled metric.

    Metrics without a trustworthy source label are deliberately not modelled as
    cards.  The composer can retain those values in hidden presentation data or
    compression statistics without inventing a human-facing label.
    """

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: str = Field(min_length=1)
    evidence: PresentationEvidence

    @field_validator("key", "label", "value")
    @classmethod
    def validate_text(cls, value: str, info: object) -> str:
        """Require stable, readable metric content before rendering."""
        return _non_blank(value, getattr(info, "field_name", "Metric value"))


class EvidenceTable(_PresentationBaseModel):
    """A compact deterministic table used by the evidence-summary section."""

    title: str = Field(min_length=1)
    columns: tuple[str, ...] = Field(min_length=1)
    rows: tuple[tuple[str, ...], ...] = Field(default_factory=tuple)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        """Require a readable table title."""
        return _non_blank(value, "Evidence table title")

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require unique, nonblank table headings."""
        return _non_blank_unique_text(value, "Evidence table columns")

    @field_validator("rows")
    @classmethod
    def validate_rows(cls, value: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
        """Reject blank table cells while retaining caller row order."""
        for row in value:
            if any(not cell.strip() for cell in row):
                raise ValueError("Evidence table rows must not contain blank cells.")
        return value

    @model_validator(mode="after")
    def validate_row_widths(self) -> "EvidenceTable":
        """Ensure templates can render every table deterministically."""
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Evidence table row widths must match its columns.")
        return self


class AppendixGroup(_PresentationBaseModel):
    """One non-primary collection retained in the composed appendix."""

    heading: str = Field(min_length=1)
    findings: tuple[InsightCard, ...] = Field(default_factory=tuple)
    concepts: tuple[ConceptCard, ...] = Field(default_factory=tuple)
    entities: tuple[EntityPresentationGroup, ...] = Field(default_factory=tuple)
    references: tuple[ReferenceCard, ...] = Field(default_factory=tuple)
    evidence_tables: tuple[EvidenceTable, ...] = Field(default_factory=tuple)

    @field_validator("heading")
    @classmethod
    def validate_heading(cls, value: str) -> str:
        """Require an intelligible appendix group label."""
        return _non_blank(value, "Appendix group heading")

    @model_validator(mode="after")
    def validate_has_content(self) -> "AppendixGroup":
        """Avoid empty presentation-only groups that add no report value."""
        if not (
            self.findings
            or self.concepts
            or self.entities
            or self.references
            or self.evidence_tables
        ):
            raise ValueError("AppendixGroup must contain at least one item.")
        return self


class HiddenPresentationData(_PresentationBaseModel):
    """Eligible but mode-excluded cards retained for later export policies.

    This is intentionally presentation-only data.  It neither changes nor
    replaces the canonical enhanced report, and renderers must not expose it
    for a mode whose composed sections did not select it.
    """

    findings: tuple[InsightCard, ...] = Field(default_factory=tuple)
    concepts: tuple[ConceptCard, ...] = Field(default_factory=tuple)
    entity_groups: tuple[EntityPresentationGroup, ...] = Field(default_factory=tuple)
    metrics: tuple[MetricCard, ...] = Field(default_factory=tuple)
    unlabeled_metrics: tuple[str, ...] = Field(default_factory=tuple)
    timeline: tuple[TimelineCard, ...] = Field(default_factory=tuple)
    references: tuple[ReferenceCard, ...] = Field(default_factory=tuple)

    @field_validator("unlabeled_metrics")
    @classmethod
    def validate_unlabeled_metrics(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Retain bare extracted values without inventing a display label."""
        return _non_blank_unique_text(value, "Hidden unlabeled metrics")

    @model_validator(mode="after")
    def validate_unique_hidden_items(self) -> "HiddenPresentationData":
        """Keep retained inventory addressable without changing its order."""
        collections = (
            ("findings", tuple(item.key for item in self.findings)),
            ("concepts", tuple(item.key for item in self.concepts)),
            ("metrics", tuple(item.key for item in self.metrics)),
        )
        for field_name, keys in collections:
            if len(set(keys)) != len(keys):
                raise ValueError(f"Hidden {field_name} must have unique keys.")

        categories = tuple(group.category for group in self.entity_groups)
        if len(set(categories)) != len(categories):
            raise ValueError("Hidden entity groups must have unique categories.")
        return self


class CompressionStatistic(_PresentationBaseModel):
    """A deterministic accounting row for one composed content category."""

    category: str = Field(min_length=1)
    extracted: int = Field(ge=0)
    displayed: int = Field(ge=0)
    moved_to_appendix: int = Field(ge=0)
    hidden: int = Field(ge=0)
    deduplicated: int = Field(ge=0)
    artifact_rejected: int = Field(ge=0)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        """Require one readable deterministic category label per row."""
        return _non_blank(value, "Compression statistic category")

    @model_validator(mode="after")
    def validate_accounting(self) -> "CompressionStatistic":
        """Require every extracted item to have exactly one terminal outcome."""
        accounted_for = (
            self.displayed
            + self.moved_to_appendix
            + self.hidden
            + self.deduplicated
            + self.artifact_rejected
        )
        if accounted_for != self.extracted:
            raise ValueError(
                "CompressionStatistic counts must partition extracted items."
            )
        return self


class PresentationSection(_PresentationBaseModel):
    """One typed, anchor-bearing section in the fixed composed report order."""

    key: PresentationSectionKey
    heading: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)
    intro: tuple[str, ...] = Field(default_factory=tuple)
    finding_groups: tuple[GroupedFinding, ...] = Field(default_factory=tuple)
    concepts: tuple[ConceptCard, ...] = Field(default_factory=tuple)
    entity_groups: tuple[EntityPresentationGroup, ...] = Field(default_factory=tuple)
    timeline: tuple[TimelineCard, ...] = Field(default_factory=tuple)
    evidence_tables: tuple[EvidenceTable, ...] = Field(default_factory=tuple)
    appendix_groups: tuple[AppendixGroup, ...] = Field(default_factory=tuple)
    references: tuple[ReferenceCard, ...] = Field(default_factory=tuple)

    @field_validator("heading")
    @classmethod
    def validate_heading(cls, value: str) -> str:
        """Require readable, stable headings for document navigation."""
        return _non_blank(value, "Section heading")

    @field_validator("anchor_id")
    @classmethod
    def validate_anchor_id(cls, value: str) -> str:
        """Restrict anchors to deterministic ASCII fragment identifiers."""
        if not _ANCHOR_PATTERN.fullmatch(value):
            raise ValueError("anchor_id must be lowercase ASCII kebab-case.")
        return value

    @field_validator("intro")
    @classmethod
    def validate_intro(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require nonblank preamble paragraphs when present."""
        return _non_blank_unique_text(value, "Section intro")


class TableOfContentsEntry(_PresentationBaseModel):
    """One ordered navigation target projected from a presentation section."""

    heading: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)

    @field_validator("heading")
    @classmethod
    def validate_heading(cls, value: str) -> str:
        """Reject blank table-of-contents headings."""
        return _non_blank(value, "TOC heading")

    @field_validator("anchor_id")
    @classmethod
    def validate_anchor_id(cls, value: str) -> str:
        """Use the same fragment restrictions as its target section."""
        if not _ANCHOR_PATTERN.fullmatch(value):
            raise ValueError("TOC anchor_id must be lowercase ASCII kebab-case.")
        return value


class TableOfContents(_PresentationBaseModel):
    """Immutable ordered navigation projected solely from composed sections."""

    entries: tuple[TableOfContentsEntry, ...] = Field(min_length=1)

    @field_validator("entries")
    @classmethod
    def validate_unique_anchors(
        cls,
        value: tuple[TableOfContentsEntry, ...],
    ) -> tuple[TableOfContentsEntry, ...]:
        """Reject duplicate navigation targets before renderer consumption."""
        anchors = tuple(entry.anchor_id for entry in value)
        if len(set(anchors)) != len(anchors):
            raise ValueError("Table of contents anchors must be unique.")
        return value


class PresentationModel(_PresentationBaseModel):
    """The complete immutable, renderer-agnostic composed report view."""

    cover: DocumentMetadata
    table_of_contents: TableOfContents
    sections: tuple[PresentationSection, ...] = Field(min_length=1)
    mode: ReportMode = ReportMode.PROFESSIONAL
    budget: PresentationBudget = Field(default_factory=PresentationBudget.professional)
    hidden_content: HiddenPresentationData = Field(
        default_factory=HiddenPresentationData
    )
    compression_statistics: tuple[CompressionStatistic, ...] = Field(
        default_factory=tuple
    )

    @field_validator("compression_statistics")
    @classmethod
    def validate_compression_categories(
        cls,
        value: tuple[CompressionStatistic, ...],
    ) -> tuple[CompressionStatistic, ...]:
        """Keep ordered compression rows unambiguous for every renderer."""
        categories = tuple(statistic.category for statistic in value)
        if len(set(categories)) != len(categories):
            raise ValueError("Compression statistic categories must be unique.")
        return value

    @model_validator(mode="after")
    def validate_fixed_section_navigation(self) -> "PresentationModel":
        """Guarantee section and TOC order are data-driven and identical."""
        expected_sections = PRESENTATION_SECTION_SPECS
        actual_sections = tuple(
            (section.key, section.heading, section.anchor_id)
            for section in self.sections
        )
        if actual_sections != expected_sections:
            raise ValueError(
                "PresentationModel sections must match the fixed presentation order."
            )

        expected_entries = tuple(
            TableOfContentsEntry(heading=heading, anchor_id=anchor_id)
            for _, heading, anchor_id in self.sections_as_specs()
        )
        if self.table_of_contents.entries != expected_entries:
            raise ValueError(
                "Table of contents entries must be the ordered section projection."
            )
        return self

    def sections_as_specs(
        self,
    ) -> tuple[tuple[PresentationSectionKey, str, str], ...]:
        """Return the fixed section projection without exposing mutable state."""
        return tuple(
            (section.key, section.heading, section.anchor_id)
            for section in self.sections
        )
