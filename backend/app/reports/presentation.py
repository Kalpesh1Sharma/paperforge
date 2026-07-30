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
    references: tuple[str, ...]
    confidence_label: str | None
    source_count: int


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
class RenderFindingGroup:
    """A render-only deterministic group of canonical finding views."""

    heading: str
    findings: tuple[RenderFinding, ...]


@dataclass(frozen=True)
class _PresentationConfig:
    """Private immutable limits for the shared enhanced-report view."""

    max_entities_per_category: int = 8

    def __post_init__(self) -> None:
        """Reject invalid private configuration without exposing a renderer API."""
        if (
            isinstance(self.max_entities_per_category, bool)
            or not isinstance(self.max_entities_per_category, int)
            or self.max_entities_per_category < 1
        ):
            raise ValueError("max_entities_per_category must be a positive integer.")


@dataclass(frozen=True)
class _ConfidenceSignal:
    """Private evidence inputs used solely for display-confidence calibration."""

    key: tuple[str, ...]
    raw_confidence: float
    source_count: int
    reference_count: int


class _DisplayConfidenceCalibrator:
    """Map raw evidence signals to stable, broad presentation percentages.

    The model-layer confidence remains untouched.  The calibration ranks the
    lexicographic evidence tuple (raw confidence first, then evidence and
    reference richness), so richer evidence can distinguish equal-confidence
    values without allowing a lower raw confidence to outrank a higher one.
    """

    _FLOOR = 60
    _CEILING = 100

    def __init__(self, signals: tuple[_ConfidenceSignal, ...]) -> None:
        """Pre-compute immutable labels for one render context."""
        self._labels = self._build_labels(signals)

    def label_for(self, key: tuple[str, ...]) -> str | None:
        """Return a display label when the item has intelligent confidence."""
        return self._labels.get(key)

    @classmethod
    def _build_labels(
        cls,
        signals: tuple[_ConfidenceSignal, ...],
    ) -> dict[tuple[str, ...], str]:
        """Create monotonic 60–100% labels without modifying source models."""
        if not signals:
            return {}

        descriptors: dict[tuple[float, int, int], list[tuple[str, ...]]] = {}
        for signal in signals:
            descriptor = (
                signal.raw_confidence,
                min(3, signal.source_count),
                min(2, signal.reference_count),
            )
            descriptors.setdefault(descriptor, []).append(signal.key)

        ranked = sorted(descriptors)
        labels: dict[tuple[str, ...], str] = {}
        if len(ranked) == 1:
            raw_confidence, source_count, reference_count = ranked[0]
            evidence_richness = min(1.0, source_count / 3.0)
            reference_richness = min(1.0, reference_count / 2.0)
            # A lone value has no peer distribution to broaden against.  The
            # source-backed tie signals make its display confidence meaningful
            # while retaining the private floor and ceiling guarantees.
            relative = min(
                1.0,
                (raw_confidence * 0.85)
                + (evidence_richness * 0.10)
                + (reference_richness * 0.05),
            )
            percentage = cls._FLOOR + round(
                (cls._CEILING - cls._FLOOR) * relative
            )
            for key in descriptors[ranked[0]]:
                labels[key] = f"{percentage}%"
            return labels

        spread = cls._CEILING - cls._FLOOR
        for index, descriptor in enumerate(ranked):
            percentage = cls._FLOOR + round(spread * index / (len(ranked) - 1))
            for key in descriptors[descriptor]:
                labels[key] = f"{percentage}%"
        return labels


_DEFAULT_PRESENTATION_CONFIG = _PresentationConfig()

_FINDING_GROUP_RULES: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "History",
        frozenset(
            {
                "history",
                "introduced",
                "published",
                "established",
                "launched",
                "announced",
                "origin",
            }
        ),
    ),
    (
        "Standards",
        frozenset(
            {
                "standard",
                "standards",
                "iso",
                "compliance",
                "approved",
                "adopted",
                "specification",
            }
        ),
    ),
    (
        "Architecture",
        frozenset(
            {
                "architecture",
                "pipeline",
                "component",
                "components",
                "system",
                "systems",
                "integration",
                "api",
            }
        ),
    ),
    (
        "Features",
        frozenset({"feature", "features", "capability", "capabilities"}),
    ),
    (
        "Performance",
        frozenset(
            {"performance", "latency", "throughput", "speed", "efficient"}
        ),
    ),
    (
        "Security",
        frozenset(
            {"security", "secure", "encryption", "signature", "privacy"}
        ),
    ),
    (
        "Accessibility",
        frozenset(
            {"accessibility", "accessible", "screen", "reader", "wcag"}
        ),
    ),
    (
        "Libraries",
        frozenset(
            {"library", "libraries", "package", "packages", "dependency"}
        ),
    ),
    (
        "Formats",
        frozenset(
            {"format", "formats", "pdf", "docx", "markdown", "file"}
        ),
    ),
)
_GENERAL_FINDING_GROUP = "General"


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
    finding_groups: tuple[RenderFindingGroup, ...]
    appendix_findings: tuple[RenderFinding, ...]
    appendix_finding_groups: tuple[RenderFindingGroup, ...]
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
        *,
        _config: _PresentationConfig = _DEFAULT_PRESENTATION_CONFIG,
    ) -> "EnhancedReportRenderContext":
        """Build one stable context, using deterministic fields as a fallback."""
        citation_index = CitationIndex.from_report(report)
        intelligence = report.report_intelligence
        finding_overrides = cls._finding_overrides(intelligence)
        visible_intelligent_entities = cls._visible_intelligent_entities(
            report,
            _config,
        )
        calibrator = cls._confidence_calibrator(
            report,
            visible_intelligent_entities,
        )
        findings = cls._findings(
            report.findings,
            "finding",
            finding_overrides,
            citation_index,
            calibrator,
        )
        appendix_findings = cls._findings(
            report.appendix_findings,
            "appendix",
            finding_overrides,
            citation_index,
            calibrator,
        )
        entity_groups = cls._entity_groups(
            report,
            citation_index,
            visible_intelligent_entities,
            calibrator,
        )
        definitions = cls._definitions(report, citation_index, calibrator)
        timeline = cls._timeline(report, citation_index, calibrator)
        sections = tuple(
            RenderSection(
                heading=section.heading,
                content=section.content,
                source_labels=cls._source_labels(
                    citation_index,
                    section.supporting_chunk_ids,
                ),
            )
            for section in report.sections
        )
        visible_source_ids = cls._visible_source_ids(
            report,
            visible_intelligent_entities,
        )

        return cls(
            report=report,
            citation_index=citation_index,
            findings=findings,
            finding_groups=cls._finding_groups(findings),
            appendix_findings=appendix_findings,
            appendix_finding_groups=cls._finding_groups(appendix_findings),
            entity_groups=entity_groups,
            definitions=definitions,
            metrics=report.base_report.important_metrics,
            timeline=timeline,
            sections=sections,
            references=cls._references(
                report,
                citation_index,
                visible_source_ids,
            ),
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
        calibrator: _DisplayConfidenceCalibrator,
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
                    confidence_label=calibrator.label_for(
                        cls._finding_confidence_key(source_kind, index)
                    ),
                    source_count=len(enriched.supporting_chunk_ids),
                )
            )
        return tuple(rendered)

    @classmethod
    def _entity_groups(
        cls,
        report: EnhancedResearchReport,
        citation_index: CitationIndex,
        visible_intelligent_entities: tuple[
            tuple["EntityGroup", tuple["NormalizedEntity", ...]], ...
        ],
        calibrator: _DisplayConfidenceCalibrator,
    ) -> tuple[RenderEntityGroup, ...]:
        """Render intelligent entity categories or retain deterministic entities."""
        intelligence = report.report_intelligence
        if intelligence is not None and intelligence.entity_groups:
            return tuple(
                RenderEntityGroup(
                    category=group.category,
                    entities=tuple(
                        cls._entity(
                            entity,
                            citation_index,
                            calibrator,
                            cls._entity_confidence_key(group.category, index),
                        )
                        for index, entity in enumerate(entities)
                    ),
                )
                for group, entities in visible_intelligent_entities
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
                        references=(),
                        confidence_label=None,
                        source_count=0,
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
        calibrator: _DisplayConfidenceCalibrator,
        confidence_key: tuple[str, ...],
    ) -> RenderEntity:
        """Convert one normalized entity without exposing its internal IDs."""
        return RenderEntity(
            name=entity.name,
            aliases=entity.aliases,
            source_labels=cls._source_labels(
                citation_index,
                entity.supporting_chunk_ids,
            ),
            references=entity.references,
            confidence_label=calibrator.label_for(confidence_key),
            source_count=len(entity.supporting_chunk_ids),
        )

    @classmethod
    def _definitions(
        cls,
        report: EnhancedResearchReport,
        citation_index: CitationIndex,
        calibrator: _DisplayConfidenceCalibrator,
    ) -> tuple[RenderDefinition, ...]:
        """Render intelligent definitions or deterministic definition strings."""
        intelligence = report.report_intelligence
        if intelligence is not None and intelligence.definitions:
            return tuple(
                cls._definition(
                    definition,
                    citation_index,
                    calibrator,
                    cls._definition_confidence_key(index),
                )
                for index, definition in enumerate(intelligence.definitions)
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
        calibrator: _DisplayConfidenceCalibrator,
        confidence_key: tuple[str, ...],
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
            confidence_label=calibrator.label_for(confidence_key),
            source_count=len(definition.supporting_chunk_ids),
        )

    @classmethod
    def _timeline(
        cls,
        report: EnhancedResearchReport,
        citation_index: CitationIndex,
        calibrator: _DisplayConfidenceCalibrator,
    ) -> tuple[RenderTimelineEvent, ...]:
        """Render intelligent timeline details or canonical timeline events."""
        intelligence = report.report_intelligence
        if intelligence is not None and intelligence.timeline:
            return tuple(
                cls._intelligent_timeline_event(
                    event,
                    citation_index,
                    calibrator,
                    cls._timeline_confidence_key(index),
                )
                for index, event in enumerate(intelligence.timeline)
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
        calibrator: _DisplayConfidenceCalibrator,
        confidence_key: tuple[str, ...],
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
            confidence_label=calibrator.label_for(confidence_key),
            source_count=len(event.supporting_chunk_ids),
        )

    @classmethod
    def _visible_intelligent_entities(
        cls,
        report: EnhancedResearchReport,
        config: _PresentationConfig,
    ) -> tuple[tuple["EntityGroup", tuple["NormalizedEntity", ...]], ...]:
        """Apply entity limits only to this transient render context.

        ``ReportIntelligence`` remains the complete ranked source of truth; the
        slice below is intentionally not retained on any immutable report model.
        """
        intelligence = report.report_intelligence
        if intelligence is None or not intelligence.entity_groups:
            return ()

        visible_groups: list[
            tuple["EntityGroup", tuple["NormalizedEntity", ...]]
        ] = []
        for group in intelligence.entity_groups:
            entities = tuple(group.entities[: config.max_entities_per_category])
            if entities:
                visible_groups.append((group, entities))
        return tuple(visible_groups)

    @classmethod
    def _confidence_calibrator(
        cls,
        report: EnhancedResearchReport,
        visible_intelligent_entities: tuple[
            tuple["EntityGroup", tuple["NormalizedEntity", ...]], ...
        ],
    ) -> _DisplayConfidenceCalibrator:
        """Collect only displayed intelligent values for private calibration."""
        intelligence = report.report_intelligence
        if intelligence is None:
            return _DisplayConfidenceCalibrator(())

        signals: list[_ConfidenceSignal] = []
        for index, finding in enumerate(intelligence.findings):
            signals.append(
                _ConfidenceSignal(
                    key=cls._finding_confidence_key(
                        finding.source_kind,
                        finding.source_index,
                    ),
                    raw_confidence=finding.confidence,
                    source_count=len(finding.supporting_chunk_ids),
                    reference_count=len(finding.references),
                )
            )
        for group, entities in visible_intelligent_entities:
            for index, entity in enumerate(entities):
                signals.append(
                    _ConfidenceSignal(
                        key=cls._entity_confidence_key(group.category, index),
                        raw_confidence=entity.confidence,
                        source_count=len(entity.supporting_chunk_ids),
                        reference_count=len(entity.references),
                    )
                )
        for index, definition in enumerate(intelligence.definitions):
            signals.append(
                _ConfidenceSignal(
                    key=cls._definition_confidence_key(index),
                    raw_confidence=definition.confidence,
                    source_count=len(definition.supporting_chunk_ids),
                    reference_count=len(definition.references),
                )
            )
        for index, event in enumerate(intelligence.timeline):
            signals.append(
                _ConfidenceSignal(
                    key=cls._timeline_confidence_key(index),
                    raw_confidence=event.confidence,
                    source_count=len(event.supporting_chunk_ids),
                    reference_count=len(event.references),
                )
            )
        return _DisplayConfidenceCalibrator(tuple(signals))

    @staticmethod
    def _finding_confidence_key(source_kind: str, source_index: int) -> tuple[str, ...]:
        """Return a collision-free transient finding calibration key."""
        return ("finding", source_kind, str(source_index))

    @staticmethod
    def _entity_confidence_key(category: str, index: int) -> tuple[str, ...]:
        """Return a collision-free transient entity calibration key."""
        return ("entity", category, str(index))

    @staticmethod
    def _definition_confidence_key(index: int) -> tuple[str, ...]:
        """Return a collision-free transient definition calibration key."""
        return ("definition", str(index))

    @staticmethod
    def _timeline_confidence_key(index: int) -> tuple[str, ...]:
        """Return a collision-free transient timeline calibration key."""
        return ("timeline", str(index))

    @classmethod
    def _finding_groups(
        cls,
        findings: tuple[RenderFinding, ...],
    ) -> tuple[RenderFindingGroup, ...]:
        """Classify displayed findings without persisting grouping metadata."""
        grouped: dict[str, list[RenderFinding]] = {
            heading: [] for heading, _ in _FINDING_GROUP_RULES
        }
        grouped[_GENERAL_FINDING_GROUP] = []
        for finding in findings:
            grouped[cls._finding_group_for(finding)].append(finding)

        ordered_headings = tuple(
            heading for heading, _ in _FINDING_GROUP_RULES
        ) + (_GENERAL_FINDING_GROUP,)
        return tuple(
            RenderFindingGroup(heading=heading, findings=tuple(grouped[heading]))
            for heading in ordered_headings
            if grouped[heading]
        )

    @staticmethod
    def _finding_group_for(finding: RenderFinding) -> str:
        """Choose the first supported fixed category from display text."""
        tokens = {
            token.casefold()
            for token in (finding.title + " " + finding.summary).replace("/", " ").split()
        }
        normalized_tokens = {
            token.strip(".,:;!?()[]{}\"'") for token in tokens
        }
        for heading, terms in _FINDING_GROUP_RULES:
            if normalized_tokens.intersection(terms):
                return heading
        return _GENERAL_FINDING_GROUP

    @classmethod
    def _visible_source_ids(
        cls,
        report: EnhancedResearchReport,
        visible_intelligent_entities: tuple[
            tuple["EntityGroup", tuple["NormalizedEntity", ...]], ...
        ],
    ) -> tuple[UUID, ...]:
        """Collect source IDs that back currently visible report intelligence."""
        visible: list[UUID] = []
        seen: set[UUID] = set()

        def add(chunk_ids: tuple[UUID, ...]) -> None:
            for chunk_id in chunk_ids:
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    visible.append(chunk_id)

        for finding in report.findings:
            add(finding.supporting_chunk_ids)
        for finding in report.appendix_findings:
            add(finding.supporting_chunk_ids)
        for section in report.sections:
            add(section.supporting_chunk_ids)

        intelligence = report.report_intelligence
        if intelligence is None:
            for event in report.base_report.timeline:
                add(event.supporting_chunk_ids)
            return tuple(visible)

        for finding in intelligence.findings:
            add(finding.supporting_chunk_ids)
        for _group, entities in visible_intelligent_entities:
            for entity in entities:
                add(entity.supporting_chunk_ids)
        for definition in intelligence.definitions:
            add(definition.supporting_chunk_ids)
        for event in intelligence.timeline:
            add(event.supporting_chunk_ids)
        return tuple(visible)

    @classmethod
    def _references(
        cls,
        report: EnhancedResearchReport,
        citation_index: CitationIndex,
        visible_source_ids: tuple[UUID, ...],
    ) -> tuple[RenderReference, ...]:
        """Prefer consolidated intelligence references and preserve legacy sources."""
        intelligence = report.report_intelligence
        if intelligence is not None and intelligence.references:
            visible_sources = set(visible_source_ids)
            rendered: list[RenderReference] = []
            for reference in intelligence.references:
                supported_visible_ids = tuple(
                    chunk_id
                    for chunk_id in reference.supporting_chunk_ids
                    if chunk_id in visible_sources
                )
                if supported_visible_ids:
                    rendered.append(
                        cls._reference(
                            reference,
                            citation_index,
                            supported_visible_ids,
                        )
                    )
            return tuple(rendered)

        rendered: list[RenderReference] = []
        visible_labels = {
            citation_index.labels[chunk_id]
            for chunk_id in visible_source_ids
            if chunk_id in citation_index.labels
        }
        for source in citation_index.sources:
            if intelligence is not None and source.label not in visible_labels:
                continue
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
        supporting_chunk_ids: tuple[UUID, ...],
    ) -> RenderReference:
        """Convert a consolidated reference without surfacing internal UUIDs."""
        return RenderReference(
            reference=reference.reference,
            source_labels=cls._source_labels(
                citation_index,
                supporting_chunk_ids,
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
