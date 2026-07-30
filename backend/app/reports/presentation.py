"""Render-only views for optional report-intelligence overlays."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.reports.citations import CitationIndex
from app.reports.enhanced_models import EnhancedResearchReport
from app.reports.exceptions import InvalidResearchReportError
from app.reports.models import Finding, TimelineEvent

if TYPE_CHECKING:
    from app.reports.intelligence import (
        ConsolidatedDefinition,
        ConsolidatedReference,
        EnrichedFinding,
        EntityGroup,
        IntelligentTimelineEvent,
        NormalizedEntity,
    )


@dataclass(frozen=True)
class RenderFinding:
    """A finding view that never exposes internal UUIDs or ranking scores."""

    title: str
    summary: str
    source_labels: tuple[str, ...]
    references: tuple[str, ...]
    importance_label: str | None
    confidence_label: str | None
    source_count: int


@dataclass(frozen=True)
class RenderEntity:
    """A normalized entity rendered inside a categorized entity group."""

    name: str
    aliases: tuple[str, ...]
    source_labels: tuple[str, ...]


@dataclass(frozen=True)
class RenderEntityGroup:
    """A display-safe group of related normalized entities."""

    category: str | None
    entities: tuple[RenderEntity, ...]


@dataclass(frozen=True)
class RenderDefinition:
    """A display-safe consolidated definition with source evidence labels."""

    concept: str
    definition: str
    related_concepts: tuple[str, ...]
    source_labels: tuple[str, ...]
    references: tuple[str, ...]
    confidence_label: str | None
    source_count: int


@dataclass(frozen=True)
class RenderTimelineEvent:
    """A display-safe timeline event with source evidence labels."""

    date: str
    description: str
    source_labels: tuple[str, ...]
    references: tuple[str, ...]
    confidence_label: str | None
    source_count: int


@dataclass(frozen=True)
class RenderSection:
    """A provenance-bearing synthesized section prepared for presentation."""

    heading: str
    content: str
    source_labels: tuple[str, ...]


@dataclass(frozen=True)
class RenderReference:
    """One consolidated reference and its human-readable source labels."""

    reference: str | None
    source_labels: tuple[str, ...]
    consolidated: bool


@dataclass(frozen=True)
class EnhancedReportRenderContext:
    """One provider-agnostic, display-safe view of an enhanced report.

    The context preserves canonical report order and fills absent intelligence
    data from the immutable deterministic overlay. Both Markdown and HTML use
    this object so optional intelligence changes content presentation uniformly.
    """

    report: EnhancedResearchReport
    citation_index: CitationIndex
    findings: tuple[RenderFinding, ...]
    appendix_findings: tuple[RenderFinding, ...]
    entity_groups: tuple[RenderEntityGroup, ...]
    definitions: tuple[RenderDefinition, ...]
    metrics: tuple[str, ...]
    timeline: tuple[RenderTimelineEvent, ...]
    sections: tuple[RenderSection, ...]
    references: tuple[RenderReference, ...]

    @classmethod
    def from_report(
        cls,
        report: EnhancedResearchReport,
    ) -> "EnhancedReportRenderContext":
        """Build one stable context, using deterministic fields as a fallback."""
        citation_index = CitationIndex.from_report(report)
        intelligence = report.report_intelligence
        finding_overrides = cls._finding_overrides(intelligence)

        return cls(
            report=report,
            citation_index=citation_index,
            findings=cls._findings(
                report.findings,
                "finding",
                finding_overrides,
                citation_index,
            ),
            appendix_findings=cls._findings(
                report.appendix_findings,
                "appendix",
                finding_overrides,
                citation_index,
            ),
            entity_groups=cls._entity_groups(report, citation_index),
            definitions=cls._definitions(report, citation_index),
            metrics=report.base_report.important_metrics,
            timeline=cls._timeline(report, citation_index),
            sections=tuple(
                RenderSection(
                    heading=section.heading,
                    content=section.content,
                    source_labels=cls._source_labels(
                        citation_index,
                        section.supporting_chunk_ids,
                    ),
                )
                for section in report.sections
            ),
            references=cls._references(report, citation_index),
        )

    @staticmethod
    def _finding_overrides(
        intelligence: object | None,
    ) -> dict[tuple[str, int], "EnrichedFinding"]:
        """Index optional intelligent finding wording by canonical location."""
        if intelligence is None:
            return {}

        overrides: dict[tuple[str, int], EnrichedFinding] = {}
        for finding in intelligence.findings:  # type: ignore[union-attr]
            key = (finding.source_kind, finding.source_index)
            if key not in overrides:
                overrides[key] = finding
        return overrides

    @classmethod
    def _findings(
        cls,
        findings: tuple[Finding, ...],
        source_kind: str,
        overrides: dict[tuple[str, int], "EnrichedFinding"],
        citation_index: CitationIndex,
    ) -> tuple[RenderFinding, ...]:
        """Map canonical findings to optional enriched wording in source order."""
        rendered: list[RenderFinding] = []
        for index, finding in enumerate(findings):
            enriched = overrides.get((source_kind, index))
            if enriched is None:
                rendered.append(
                    RenderFinding(
                        title=finding.title,
                        summary=finding.description,
                        source_labels=cls._source_labels(
                            citation_index,
                            finding.supporting_chunk_ids,
                        ),
                        references=(),
                        importance_label=None,
                        confidence_label=None,
                        source_count=len(finding.supporting_chunk_ids),
                    )
                )
                continue

            rendered.append(
                RenderFinding(
                    title=enriched.title,
                    summary=enriched.summary,
                    source_labels=cls._source_labels(
                        citation_index,
                        enriched.supporting_chunk_ids,
                    ),
                    references=enriched.references,
                    importance_label=cls._importance_label(enriched.importance),
                    confidence_label=cls._confidence_label(enriched.confidence),
                    source_count=len(enriched.supporting_chunk_ids),
                )
            )
        return tuple(rendered)

    @classmethod
    def _entity_groups(
        cls,
        report: EnhancedResearchReport,
        citation_index: CitationIndex,
    ) -> tuple[RenderEntityGroup, ...]:
        """Render intelligent entity categories or retain deterministic entities."""
        intelligence = report.report_intelligence
        if intelligence is not None and intelligence.entity_groups:
            return tuple(
                RenderEntityGroup(
                    category=group.category,
                    entities=tuple(
                        cls._entity(entity, citation_index)
                        for entity in group.entities
                    ),
                )
                for group in intelligence.entity_groups
            )

        entities = report.base_report.important_entities
        if not entities:
            return ()
        return (
            RenderEntityGroup(
                category=None,
                entities=tuple(
                    RenderEntity(
                        name=entity,
                        aliases=(),
                        source_labels=(),
                    )
                    for entity in entities
                ),
            ),
        )

    @classmethod
    def _entity(
        cls,
        entity: "NormalizedEntity",
        citation_index: CitationIndex,
    ) -> RenderEntity:
        """Convert one normalized entity without exposing its internal IDs."""
        return RenderEntity(
            name=entity.name,
            aliases=entity.aliases,
            source_labels=cls._source_labels(
                citation_index,
                entity.supporting_chunk_ids,
            ),
        )

    @classmethod
    def _definitions(
        cls,
        report: EnhancedResearchReport,
        citation_index: CitationIndex,
    ) -> tuple[RenderDefinition, ...]:
        """Render intelligent definitions or deterministic definition strings."""
        intelligence = report.report_intelligence
        if intelligence is not None and intelligence.definitions:
            return tuple(
                cls._definition(definition, citation_index)
                for definition in intelligence.definitions
            )

        return tuple(
            RenderDefinition(
                concept=definition,
                definition=definition,
                related_concepts=(),
                source_labels=(),
                references=(),
                confidence_label=None,
                source_count=0,
            )
            for definition in report.base_report.important_definitions
        )

    @classmethod
    def _definition(
        cls,
        definition: "ConsolidatedDefinition",
        citation_index: CitationIndex,
    ) -> RenderDefinition:
        """Convert one consolidated definition to a display-safe view."""
        return RenderDefinition(
            concept=definition.concept,
            definition=definition.definition,
            related_concepts=definition.related_concepts,
            source_labels=cls._source_labels(
                citation_index,
                definition.supporting_chunk_ids,
            ),
            references=definition.references,
            confidence_label=cls._confidence_label(definition.confidence),
            source_count=len(definition.supporting_chunk_ids),
        )

    @classmethod
    def _timeline(
        cls,
        report: EnhancedResearchReport,
        citation_index: CitationIndex,
    ) -> tuple[RenderTimelineEvent, ...]:
        """Render intelligent timeline details or canonical timeline events."""
        intelligence = report.report_intelligence
        if intelligence is not None and intelligence.timeline:
            return tuple(
                cls._intelligent_timeline_event(event, citation_index)
                for event in intelligence.timeline
            )

        return tuple(
            cls._timeline_event(event, citation_index)
            for event in report.base_report.timeline
        )

    @classmethod
    def _timeline_event(
        cls,
        event: TimelineEvent,
        citation_index: CitationIndex,
    ) -> RenderTimelineEvent:
        """Convert one deterministic timeline event into a display-safe view."""
        return RenderTimelineEvent(
            date=event.date,
            description=event.description,
            source_labels=cls._source_labels(
                citation_index,
                event.supporting_chunk_ids,
            ),
            references=(),
            confidence_label=None,
            source_count=len(event.supporting_chunk_ids),
        )

    @classmethod
    def _intelligent_timeline_event(
        cls,
        event: "IntelligentTimelineEvent",
        citation_index: CitationIndex,
    ) -> RenderTimelineEvent:
        """Convert one enriched timeline event into a display-safe view."""
        return RenderTimelineEvent(
            date=event.date,
            description=event.description,
            source_labels=cls._source_labels(
                citation_index,
                event.supporting_chunk_ids,
            ),
            references=event.references,
            confidence_label=cls._confidence_label(event.confidence),
            source_count=len(event.supporting_chunk_ids),
        )

    @classmethod
    def _references(
        cls,
        report: EnhancedResearchReport,
        citation_index: CitationIndex,
    ) -> tuple[RenderReference, ...]:
        """Prefer consolidated intelligence references and preserve legacy sources."""
        intelligence = report.report_intelligence
        if intelligence is not None and intelligence.references:
            return tuple(
                cls._reference(reference, citation_index)
                for reference in intelligence.references
            )

        rendered: list[RenderReference] = []
        for source in citation_index.sources:
            if source.references:
                rendered.extend(
                    RenderReference(
                        reference=reference,
                        source_labels=(source.label,),
                        consolidated=False,
                    )
                    for reference in source.references
                )
            else:
                rendered.append(
                    RenderReference(
                        reference=None,
                        source_labels=(source.label,),
                        consolidated=False,
                    )
                )
        return tuple(rendered)

    @classmethod
    def _reference(
        cls,
        reference: "ConsolidatedReference",
        citation_index: CitationIndex,
    ) -> RenderReference:
        """Convert a consolidated reference without surfacing internal UUIDs."""
        return RenderReference(
            reference=reference.reference,
            source_labels=cls._source_labels(
                citation_index,
                reference.supporting_chunk_ids,
            ),
            consolidated=True,
        )

    @staticmethod
    def _source_labels(
        citation_index: CitationIndex,
        chunk_ids: tuple[UUID, ...],
    ) -> tuple[str, ...]:
        """Translate source UUIDs to display labels and reject unknown evidence."""
        try:
            return citation_index.labels_for(chunk_ids)
        except KeyError as exc:
            raise InvalidResearchReportError(
                "Rendered intelligence referenced an unknown source chunk."
            ) from exc

    @staticmethod
    def _importance_label(value: object) -> str:
        """Return a human-readable importance label without any numeric score."""
        raw_value = getattr(value, "value", value)
        if not isinstance(raw_value, str):
            raise InvalidResearchReportError(
                "Intelligent finding importance must be text."
            )
        return raw_value

    @staticmethod
    def _confidence_label(confidence: float) -> str:
        """Render an auditable rounded confidence percentage."""
        return f"{round(confidence * 100)}%"
