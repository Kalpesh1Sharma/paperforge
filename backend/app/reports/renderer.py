"""Deterministic Markdown rendering for research reports."""

import math
from uuid import UUID

from pydantic import ValidationError

from app.reports.composer import ReportComposer
from app.reports.enhanced_models import (
    EnhancedResearchReport,
    SynthesisMetadata,
    SynthesisSourceEvidence,
    SynthesizedSection,
)
from app.reports.exceptions import (
    InvalidResearchReportError,
    ReportCompositionError,
    ReportRenderingError,
)
from app.reports.models import (
    Finding,
    ReportSection,
    ResearchReport,
    TimelineEvent,
)
from app.reports.presentation import (
    EnhancedReportRenderContext,
    RenderDefinition,
    RenderFinding,
    RenderFindingGroup,
    RenderReference,
    RenderTimelineEvent,
)
from app.reports.presentation_models import (
    AppendixGroup,
    ConceptCard,
    EntityCard,
    EntityPresentationGroup,
    EvidenceTable,
    GroupedFinding,
    InsightCard,
    PresentationEvidence,
    PresentationModel,
    PresentationSection,
    ReferenceCard,
    TimelineCard,
)


_PUBLICATION_VERSION = "v0.9.0"
_UNAVAILABLE = "Not available"


class MarkdownRenderer:
    """Render validated ``ResearchReport`` instances as stable Markdown."""

    def render(self, report: ResearchReport) -> str:
        """Render one report using the fixed PaperForge Markdown layout."""
        self._validate_report(report)

        try:
            return self._render_report(report)
        except InvalidResearchReportError:
            raise
        except Exception as exc:
            raise ReportRenderingError("Unable to render the research report.") from exc

    def render_enhanced(self, enhanced_report: EnhancedResearchReport) -> str:
        """Compose and render an immutable enhanced report with default metadata."""
        try:
            presentation = ReportComposer().compose(enhanced_report)
        except InvalidResearchReportError:
            raise
        except ReportCompositionError as exc:
            raise ReportRenderingError(
                "Unable to compose the enhanced research report."
            ) from exc
        return self.render_presentation(presentation)

    def render_presentation(self, presentation: PresentationModel) -> str:
        """Render one immutable, composer-produced presentation model."""
        self._validate_presentation_model(presentation)

        try:
            return self._render_presentation_model(presentation)
        except InvalidResearchReportError:
            raise
        except Exception as exc:
            raise ReportRenderingError(
                "Unable to render the composed research report."
            ) from exc

    @classmethod
    def _render_report(cls, report: ResearchReport) -> str:
        """Build Markdown sections without mutating the source report."""
        blocks = [
            f"# {report.title}",
            cls._text_block("Executive Summary", report.executive_summary),
            cls._bullet_block(
                "Key Findings",
                tuple(
                    f"- **{finding.title}**: {finding.description}"
                    for finding in report.findings
                ),
            ),
            cls._bullet_block(
                "Important Entities",
                tuple(f"- {entity}" for entity in report.important_entities),
            ),
            cls._bullet_block(
                "Definitions",
                tuple(
                    f"- {definition}"
                    for definition in report.important_definitions
                ),
            ),
            cls._bullet_block(
                "Metrics",
                tuple(f"- {metric}" for metric in report.important_metrics),
            ),
            cls._bullet_block(
                "Timeline",
                tuple(
                    f"- **{event.date}**: {event.description}"
                    for event in report.timeline
                ),
            ),
            cls._bullet_block(
                "References",
                tuple(f"- {reference}" for reference in report.references),
            ),
        ]
        blocks.extend(
            cls._text_block(section.heading, section.content)
            for section in report.sections
        )
        return "\n\n".join(block.rstrip("\n") for block in blocks) + "\n"

    @classmethod
    def _render_presentation_model(cls, presentation: PresentationModel) -> str:
        """Render the shared model as a publication-style Markdown report.

        The composer remains the sole owner of report composition.  This method
        deliberately formats its already-materialized section order, evidence,
        and anchors without deriving new report content.
        """
        reference_numbers = cls._reference_numbers(presentation)
        blocks = [
            cls._publication_cover_block(presentation),
            cls._table_of_contents_block(presentation),
        ]
        blocks.extend(
            cls._presentation_section_block(
                section,
                presentation,
                reference_numbers,
            )
            for section in presentation.sections
        )
        return "\n\n".join(block.rstrip("\n") for block in blocks) + "\n"

    @classmethod
    def _publication_cover_block(cls, presentation: PresentationModel) -> str:
        """Render a restrained publication cover without dashboard-style cards."""
        cover = presentation.cover
        prepared_from = cover.filename or _UNAVAILABLE
        generated_on = (
            cover.generated_on.isoformat()
            if cover.generated_on is not None
            else _UNAVAILABLE
        )
        return "\n".join(
            (
                f"# {cover.title}",
                "",
                f"*PaperForge Research Report - {_PUBLICATION_VERSION}*",
                "",
                f"Prepared from document: **{prepared_from}**  ",
                "Prepared by PaperForge",
                "",
                "| Publication detail | Value |",
                "| --- | --- |",
                f"| Research domain | {cover.domain} |",
                f"| Report status | {cover.status} |",
                f"| Generated | {generated_on} |",
            )
        )

    @staticmethod
    def _table_of_contents_block(presentation: PresentationModel) -> str:
        """Render the model-owned section projection as a numbered TOC."""
        entries = tuple(
            "{number}. [{heading}](#{anchor})".format(
                number=index,
                heading=entry.heading,
                anchor=entry.anchor_id,
            )
            for index, entry in enumerate(
                presentation.table_of_contents.entries,
                start=1,
            )
        )
        return "## Table of Contents\n\n" + "\n".join(entries)

    @classmethod
    def _presentation_section_block(
        cls,
        section: PresentationSection,
        presentation: PresentationModel,
        reference_numbers: dict[int, int],
    ) -> str:
        """Render one immutable section in the model's supplied order."""
        blocks: list[str] = [f"## {section.heading}"]

        if section.key == "document-overview":
            blocks.extend(section.intro[:1])
            blocks.append(cls._document_information_block(presentation))
        else:
            blocks.extend(section.intro)

        for group in section.finding_groups:
            blocks.append(
                cls._presentation_finding_group_block(
                    group,
                    heading_level=3,
                )
            )

        for group in section.entity_groups:
            blocks.append(
                cls._presentation_entity_group_block(group, heading_level=3)
            )

        if section.concepts:
            blocks.extend(
                cls._presentation_concept_entry(
                    concept,
                    heading_level=3,
                )
                for concept in section.concepts
            )

        if section.timeline:
            blocks.extend(
                cls._presentation_timeline_entry(
                    event,
                    heading_level=3,
                )
                for event in section.timeline
            )

        for index, table in enumerate(section.evidence_tables, start=1):
            blocks.append(cls._presentation_table_block(table, index))

        for appendix_group in section.appendix_groups:
            blocks.append(
                cls._presentation_appendix_group_block(
                    appendix_group,
                    reference_numbers,
                )
            )

        if section.references:
            blocks.append(
                "### References\n\n"
                + cls._publication_reference_list(
                    section.references,
                    reference_numbers,
                )
            )

        if len(blocks) == 1:
            empty_text = (
                "No supplementary material is available."
                if section.key == "appendix"
                else "No material is available for this section."
            )
            blocks.append(empty_text)
        return "\n\n".join(blocks)

    @classmethod
    def _document_information_block(cls, presentation: PresentationModel) -> str:
        """Render document metadata as a compact publication table."""
        cover = presentation.cover
        confidence = cls._confidence_text(cover.mean_confidence)
        generated_on = (
            cover.generated_on.isoformat()
            if cover.generated_on is not None
            else _UNAVAILABLE
        )
        page_count = (
            str(cover.page_count)
            if cover.page_count is not None
            else _UNAVAILABLE
        )
        rows = (
            ("Document", cover.filename or _UNAVAILABLE),
            ("Research domain", cover.domain),
            ("Document type", cover.file_type or _UNAVAILABLE),
            ("Pages", page_count),
            ("Knowledge objects", str(cover.knowledge_object_count)),
            ("Evidence sources", str(cover.evidence_source_count)),
            ("Confidence", confidence),
            ("Status", cover.status),
            ("Provider", cover.provider or _UNAVAILABLE),
            ("Model", cover.model or "Not applicable"),
            ("Generated", generated_on),
        )
        table_rows = "\n".join(
            f"| {label} | {value} |" for label, value in rows
        )
        return "\n".join(
            (
                "### Document Information",
                "",
                "| Attribute | Details |",
                "| --- | --- |",
                table_rows,
            )
        )

    @classmethod
    def _presentation_finding_group_block(
        cls,
        group: GroupedFinding,
        *,
        heading_level: int,
    ) -> str:
        """Render evidence-backed findings as short research discussions."""
        heading = "#" * heading_level
        discussions = tuple(
            cls._presentation_finding_discussion(
                insight,
                heading_level=heading_level + 1,
            )
            for insight in group.findings
        )
        return f"{heading} {group.heading}\n\n" + "\n\n".join(discussions)

    @classmethod
    def _presentation_finding_discussion(
        cls,
        insight: InsightCard,
        *,
        heading_level: int,
    ) -> str:
        """Format one finding with narrative, evidence, and source citations."""
        evidence = insight.evidence
        heading = "#" * heading_level
        return "\n\n".join(
            (
                f"{heading} {insight.title}",
                insight.summary,
                cls._evidence_detail_block(
                    evidence,
                    importance=insight.importance,
                ),
            )
        )

    @classmethod
    def _presentation_entity_group_block(
        cls,
        group: EntityPresentationGroup,
        *,
        heading_level: int,
    ) -> str:
        """Render one concise, categorized entity list with citations."""
        heading = "#" * heading_level
        return "\n\n".join(
            (
                f"{heading} {group.category}",
                "\n".join(
                    cls._presentation_entity_item(entity)
                    for entity in group.entities
                ),
            )
        )

    @classmethod
    def _presentation_entity_item(cls, entity: EntityCard) -> str:
        """Render a categorized entity without turning it into a dashboard chip."""
        evidence = entity.evidence
        aliases = (
            f" (also known as: {', '.join(entity.aliases)})"
            if entity.aliases
            else ""
        )
        details = [f"- **{entity.name}**{aliases}"]
        evidence_line = cls._compact_evidence_line(evidence)
        if evidence_line:
            details.append(f"  - {evidence_line}")
        return "\n".join(details)

    @classmethod
    def _presentation_concept_entry(
        cls,
        concept: ConceptCard,
        *,
        heading_level: int,
    ) -> str:
        """Render a concept as a readable, provenance-bearing reference entry."""
        evidence = concept.evidence
        heading = "#" * heading_level
        details = [f"{heading} {concept.concept}", concept.definition]
        if concept.why_it_matters is not None:
            details.append(f"**Why it matters:** {concept.why_it_matters}")
        if concept.related_concepts:
            details.append(
                "**Related concepts:** " + ", ".join(concept.related_concepts)
            )
        details.append(cls._evidence_detail_block(evidence))
        return "\n\n".join(details)

    @classmethod
    def _presentation_timeline_entry(
        cls,
        event: TimelineCard,
        *,
        heading_level: int,
    ) -> str:
        """Render one composer-ordered historical event as a publication entry."""
        evidence = event.evidence
        heading = "#" * heading_level
        return "\n\n".join(
            (
                f"{heading} {event.date}",
                event.description,
                cls._evidence_detail_block(evidence),
            )
        )

    @staticmethod
    def _presentation_table_block(
        table: EvidenceTable,
        ordinal: int,
        *,
        heading_level: int = 3,
    ) -> str:
        """Render one deterministic visible evidence table with a stable caption."""
        columns = tuple(table.columns)
        header = "| " + " | ".join(columns) + " |"
        divider = "| " + " | ".join("---" for _ in columns) + " |"
        rows = tuple(
            "| "
            + " | ".join(
                str(value).replace("\r", " ").replace("\n", " ").replace(
                    "|",
                    "\\|",
                )
                for value in row
            )
            + " |"
            for row in table.rows
        )
        heading = "#" * heading_level
        return "{heading} Table {ordinal}. {title}\n\n{table}".format(
            heading=heading,
            ordinal=ordinal,
            title=table.title,
            table="\n".join((header, divider, *rows)),
        )

    @classmethod
    def _presentation_appendix_group_block(
        cls,
        appendix_group: AppendixGroup,
        reference_numbers: dict[int, int],
    ) -> str:
        """Render supplemental material with publication-style hierarchy."""
        blocks = [f"### {appendix_group.heading}"]
        if appendix_group.findings:
            blocks.append(
                "\n\n".join(
                    cls._presentation_finding_discussion(
                        finding,
                        heading_level=4,
                    )
                    for finding in appendix_group.findings
                )
            )
        if appendix_group.concepts:
            blocks.append(
                "\n\n".join(
                    cls._presentation_concept_entry(
                        concept,
                        heading_level=4,
                    )
                    for concept in appendix_group.concepts
                )
            )
        for entity_group in appendix_group.entities:
            blocks.append(
                cls._presentation_entity_group_block(
                    entity_group,
                    heading_level=4,
                )
            )
        if appendix_group.references:
            blocks.append(
                cls._publication_reference_list(
                    appendix_group.references,
                    reference_numbers,
                )
            )
        for index, table in enumerate(appendix_group.evidence_tables, start=1):
            blocks.append(
                cls._presentation_table_block(
                    table,
                    index,
                    heading_level=4,
                )
            )
        return "\n\n".join(blocks)

    @classmethod
    def _evidence_detail_block(
        cls,
        evidence: PresentationEvidence,
        *,
        importance: str | None = None,
    ) -> str:
        """Format a compact evidence statement from an immutable evidence view."""
        details: list[str] = []
        if importance is not None:
            details.append(f"Importance: {importance}")
        confidence_label = evidence.confidence_label
        if confidence_label is not None:
            details.append(f"Confidence: {confidence_label}")
        source_count = evidence.source_count
        if source_count:
            details.append(
                "Evidence: {count} {label}".format(
                    count=source_count,
                    label="source" if source_count == 1 else "sources",
                )
            )
        labels = evidence.source_labels
        if labels:
            details.append("Sources: " + ", ".join(labels))
        return "*" + "; ".join(details) + "*" if details else ""

    @classmethod
    def _compact_evidence_line(cls, evidence: PresentationEvidence) -> str:
        """Return inline entity provenance without repeating a card-style block."""
        details: list[str] = []
        confidence_label = evidence.confidence_label
        if confidence_label is not None:
            details.append(f"Confidence: {confidence_label}")
        labels = evidence.source_labels
        if labels:
            details.append("Sources: " + ", ".join(labels))
        return "; ".join(details)

    @staticmethod
    def _confidence_text(confidence: float | None) -> str:
        """Format optional raw cover confidence without inventing a value."""
        if confidence is None:
            return _UNAVAILABLE
        return f"{round(confidence * 100)}%"

    @staticmethod
    def _reference_numbers(presentation: PresentationModel) -> dict[int, int]:
        """Assign stable publication-reference numbers in model section order."""
        numbers: dict[int, int] = {}
        next_number = 1
        for section in presentation.sections:
            for reference in section.references:
                numbers[id(reference)] = next_number
                next_number += 1
            for appendix_group in section.appendix_groups:
                for reference in appendix_group.references:
                    numbers[id(reference)] = next_number
                    next_number += 1
        return numbers

    @classmethod
    def _publication_reference_list(
        cls,
        references: tuple[ReferenceCard, ...],
        reference_numbers: dict[int, int],
    ) -> str:
        """Render numbered reference entries with source labels, never UUIDs."""
        return "\n".join(
            "{number}. {reference}{citation}".format(
                number=reference_numbers[id(reference)],
                reference=reference.reference,
                citation=cls._source_suffix(reference.evidence.source_labels),
            )
            for reference in references
        )

    @classmethod
    def _render_enhanced_report(cls, enhanced_report: EnhancedResearchReport) -> str:
        """Render an enhancement overlay through one provider-agnostic context."""
        context = EnhancedReportRenderContext.from_report(enhanced_report)
        base_report = context.report.base_report
        blocks = [
            f"# {base_report.title}",
            cls._text_block("Executive Summary", context.report.executive_summary),
            cls._enhanced_finding_block(
                "Key Findings",
                context.finding_groups,
            ),
            cls._bullet_block(
                "Important Entities",
                cls._entity_items(context),
            ),
            cls._bullet_block(
                "Definitions",
                cls._definition_items(context.definitions),
            ),
            cls._bullet_block(
                "Metrics",
                tuple(f"- {metric}" for metric in context.metrics),
            ),
            cls._bullet_block(
                "Timeline",
                cls._timeline_items(context.timeline),
            ),
        ]
        blocks.extend(
            cls._text_block(
                section.heading,
                "{content}\n\n*Sources: {sources}*".format(
                    content=section.content,
                    sources=", ".join(section.source_labels),
                ),
            )
            for section in context.sections
        )
        blocks.append(cls._enhanced_reference_block(context.references))
        blocks.append(
            cls._enhanced_finding_block(
                "Appendix",
                context.appendix_finding_groups,
                empty_text="No additional findings.",
            )
        )
        return "\n\n".join(block.rstrip("\n") for block in blocks) + "\n"

    @staticmethod
    def _enhanced_finding_block(
        heading: str,
        finding_groups: tuple[RenderFindingGroup, ...],
        *,
        empty_text: str | None = None,
    ) -> str:
        """Render transient finding groups without changing canonical findings."""
        if not finding_groups:
            return (
                f"## {heading}\n\n{empty_text}"
                if empty_text is not None
                else f"## {heading}"
            )

        groups: list[str] = []
        for group in finding_groups:
            groups.append(
                "### {heading}\n\n{items}".format(
                    heading=group.heading,
                    items="\n".join(
                        MarkdownRenderer._enhanced_finding_items(group.findings)
                    ),
                )
            )
        return f"## {heading}\n\n" + "\n\n".join(groups)

    @staticmethod
    def _enhanced_finding_items(
        findings: tuple[RenderFinding, ...],
    ) -> tuple[str, ...]:
        """Format optional intelligence without exposing numeric scores or UUIDs."""
        items: list[str] = []
        for finding in findings:
            details = [
                "- **{title}**: {summary}{citation}".format(
                    title=finding.title,
                    summary=finding.summary,
                    citation=MarkdownRenderer._source_suffix(
                        finding.source_labels
                    ),
                )
            ]
            if finding.importance_label is not None:
                details.append(f"  - Importance: {finding.importance_label}")
            if finding.confidence_label is not None:
                details.append(f"  - Confidence: {finding.confidence_label}")
            details.append(
                "  - Evidence: {count} {label}".format(
                    count=finding.source_count,
                    label="source" if finding.source_count == 1 else "sources",
                )
            )
            if finding.references:
                details.append(
                    "  - References: " + "; ".join(finding.references)
                )
            items.append("\n".join(details))
        return tuple(items)

    @staticmethod
    def _entity_items(
        context: EnhancedReportRenderContext,
    ) -> tuple[str, ...]:
        """Render categorized entities, retaining plain deterministic fallback text."""
        items: list[str] = []
        for group in context.entity_groups:
            if group.category is not None:
                items.append(f"- **{group.category}**")
            for entity in group.entities:
                aliases = (
                    f" (also known as: {', '.join(entity.aliases)})"
                    if entity.aliases
                    else ""
                )
                item = "{name}{aliases}{citation}".format(
                    name=entity.name,
                    aliases=aliases,
                    citation=MarkdownRenderer._source_suffix(
                        entity.source_labels
                    ),
                )
                indent = "  " if group.category is not None else ""
                details = [f"{indent}- {item}"]
                if entity.confidence_label is not None:
                    detail_indent = indent + "  "
                    details.append(
                        f"{detail_indent}- Confidence: {entity.confidence_label}"
                    )
                    details.append(
                        "{indent}- Evidence: {count} {label}".format(
                            indent=detail_indent,
                            count=entity.source_count,
                            label=(
                                "source"
                                if entity.source_count == 1
                                else "sources"
                            ),
                        )
                    )
                if entity.references:
                    details.append(
                        f"{indent}  - References: {'; '.join(entity.references)}"
                    )
                items.append("\n".join(details))
        return tuple(items)

    @staticmethod
    def _definition_items(
        definitions: tuple[RenderDefinition, ...],
    ) -> tuple[str, ...]:
        """Render definitions with optional confidence and evidence information."""
        items: list[str] = []
        for definition in definitions:
            is_plain_fallback = (
                definition.concept == definition.definition
                and not definition.related_concepts
                and definition.confidence_label is None
                and definition.source_count == 0
            )
            if is_plain_fallback:
                items.append(f"- {definition.definition}")
                continue

            details = [
                "- **{concept}**: {definition}{citation}".format(
                    concept=definition.concept,
                    definition=definition.definition,
                    citation=MarkdownRenderer._source_suffix(
                        definition.source_labels
                    ),
                )
            ]
            if definition.related_concepts:
                details.append(
                    "  - Related concepts: "
                    + ", ".join(definition.related_concepts)
                )
            if definition.confidence_label is not None:
                details.append(
                    f"  - Confidence: {definition.confidence_label}"
                )
            details.append(
                "  - Evidence: {count} {label}".format(
                    count=definition.source_count,
                    label="source" if definition.source_count == 1 else "sources",
                )
            )
            if definition.references:
                details.append(
                    "  - References: " + "; ".join(definition.references)
                )
            items.append("\n".join(details))
        return tuple(items)

    @staticmethod
    def _timeline_items(
        timeline: tuple[RenderTimelineEvent, ...],
    ) -> tuple[str, ...]:
        """Render timeline events with optional confidence and evidence details."""
        items: list[str] = []
        for event in timeline:
            details = [
                "- **{date}**: {description}{citation}".format(
                    date=event.date,
                    description=event.description,
                    citation=MarkdownRenderer._source_suffix(event.source_labels),
                )
            ]
            if event.confidence_label is not None:
                details.append(f"  - Confidence: {event.confidence_label}")
            details.append(
                "  - Evidence: {count} {label}".format(
                    count=event.source_count,
                    label="source" if event.source_count == 1 else "sources",
                )
            )
            if event.references:
                details.append("  - References: " + "; ".join(event.references))
            items.append("\n".join(details))
        return tuple(items)

    @staticmethod
    def _enhanced_reference_block(
        references: tuple[RenderReference, ...],
    ) -> str:
        """Render consolidated references with human source labels only."""
        if not references:
            return "## References"

        if all(not reference.consolidated for reference in references):
            return MarkdownRenderer._legacy_reference_block(references)

        items: list[str] = []
        for reference in references:
            labels = ", ".join(reference.source_labels)
            if reference.reference is None:
                items.append(f"- **{labels}**")
            else:
                items.append(
                    "- {reference} [{labels}]".format(
                        reference=reference.reference,
                        labels=labels,
                    )
                )
        return "## References\n\n" + "\n".join(items)

    @staticmethod
    def _legacy_reference_block(
        references: tuple[RenderReference, ...],
    ) -> str:
        """Preserve legacy source-entry layout when no consolidation is available."""
        grouped: dict[tuple[str, ...], list[str]] = {}
        for reference in references:
            values = grouped.setdefault(reference.source_labels, [])
            if reference.reference is not None:
                values.append(reference.reference)

        items: list[str] = []
        for labels, values in grouped.items():
            source_label = ", ".join(labels)
            if values:
                items.append(
                    "- **{label}**\n{references}".format(
                        label=source_label,
                        references="\n".join(
                            f"  - {reference}" for reference in values
                        ),
                    )
                )
            else:
                items.append(f"- **{source_label}**")
        return "## References\n\n" + "\n".join(items)

    @staticmethod
    def _source_suffix(source_labels: tuple[str, ...]) -> str:
        """Return a display-safe source suffix without exposing chunk UUIDs."""
        if not source_labels:
            return ""
        return f" [{', '.join(source_labels)}]"

    @staticmethod
    def _text_block(heading: str, content: str) -> str:
        """Format one titled prose section."""
        return f"## {heading}\n\n{content}"

    @staticmethod
    def _bullet_block(heading: str, items: tuple[str, ...]) -> str:
        """Format one titled bullet-list section, including an empty section."""
        if not items:
            return f"## {heading}"
        return f"## {heading}\n\n" + "\n".join(items)

    @staticmethod
    def _validate_presentation_model(presentation: object) -> None:
        """Reject malformed or validation-bypassed presentation models."""
        if not isinstance(presentation, PresentationModel):
            raise InvalidResearchReportError(
                "Input must be a PresentationModel instance."
            )
        if getattr(presentation, "__pydantic_extra__", None):
            raise InvalidResearchReportError(
                "PresentationModel must not contain extra fields."
            )
        try:
            PresentationModel.model_validate(
                presentation.model_dump(mode="python", warnings="error")
            )
        except (AttributeError, TypeError, ValidationError, ValueError) as exc:
            raise InvalidResearchReportError(
                "PresentationModel failed structural validation."
            ) from exc

    @classmethod
    def _validate_report(cls, report: object) -> None:
        """Reject invalid reports, including validation-bypassed model instances."""
        if not isinstance(report, ResearchReport):
            raise InvalidResearchReportError(
                "Input must be a ResearchReport instance."
            )

        cls._validate_string(report.title, "ResearchReport title")
        cls._validate_string(
            report.executive_summary,
            "ResearchReport executive_summary",
        )
        cls._validate_findings(report.findings)
        cls._validate_string_collection(
            report.important_entities,
            "ResearchReport important_entities",
        )
        cls._validate_string_collection(
            report.important_definitions,
            "ResearchReport important_definitions",
        )
        cls._validate_string_collection(
            report.important_metrics,
            "ResearchReport important_metrics",
        )
        cls._validate_timeline(report.timeline)
        cls._validate_string_collection(
            report.references,
            "ResearchReport references",
        )
        cls._validate_sections(report.sections)

        if len(set(report.important_entities)) != len(report.important_entities):
            raise InvalidResearchReportError(
                "ResearchReport important_entities must not contain duplicates."
            )
        if len(set(report.references)) != len(report.references):
            raise InvalidResearchReportError(
                "ResearchReport references must not contain duplicates."
            )

    @classmethod
    def _validate_enhanced_report(cls, enhanced_report: object) -> None:
        """Reject malformed enhanced reports before Markdown composition."""
        if not isinstance(enhanced_report, EnhancedResearchReport):
            raise InvalidResearchReportError(
                "Input must be an EnhancedResearchReport instance."
            )
        if getattr(enhanced_report, "__pydantic_extra__", None):
            raise InvalidResearchReportError(
                "EnhancedResearchReport must not contain extra fields."
            )

        try:
            payload = enhanced_report.model_dump(mode="python", warnings="error")
            EnhancedResearchReport.model_validate(payload)
        except (AttributeError, TypeError, ValidationError, ValueError) as exc:
            raise InvalidResearchReportError(
                "EnhancedResearchReport failed structural validation."
            ) from exc
        except Exception as exc:
            raise InvalidResearchReportError(
                "EnhancedResearchReport could not be validated safely."
            ) from exc

        try:
            base_report = enhanced_report.base_report
            executive_summary = enhanced_report.executive_summary
            findings = enhanced_report.findings
            appendix_findings = enhanced_report.appendix_findings
            sections = enhanced_report.sections
            synthesis_metadata = enhanced_report.synthesis_metadata
        except AttributeError as exc:
            raise InvalidResearchReportError(
                "EnhancedResearchReport is missing a required field."
            ) from exc

        try:
            cls._validate_base_report(base_report)
            cls._validate_enhanced_summary(executive_summary)
            cls._validate_enhanced_findings(findings)
            cls._validate_enhanced_findings(appendix_findings)
            cls._validate_synthesized_sections(sections)
            cls._validate_synthesis_metadata(synthesis_metadata)
        except InvalidResearchReportError:
            raise
        except Exception as exc:
            raise InvalidResearchReportError(
                "EnhancedResearchReport is malformed."
            ) from exc

    @classmethod
    def _validate_enhanced_summary(cls, summary: object) -> None:
        """Require non-empty enhanced summary text without provider policy."""
        cls._validate_string(summary, "EnhancedResearchReport executive_summary")
        if not summary.strip():
            raise InvalidResearchReportError(
                "EnhancedResearchReport executive_summary must not be blank."
            )

    @classmethod
    def _validate_base_report(cls, report: object) -> None:
        """Apply report validation while mapping bypassed-model failures safely."""
        if getattr(report, "__pydantic_extra__", None):
            raise InvalidResearchReportError(
                "ResearchReport must not contain extra fields."
            )
        try:
            cls._validate_report(report)
        except InvalidResearchReportError:
            raise
        except Exception as exc:
            raise InvalidResearchReportError(
                "EnhancedResearchReport base_report is malformed."
            ) from exc

    @classmethod
    def _validate_enhanced_findings(cls, findings: object) -> None:
        """Validate AI findings, including their required source provenance."""
        cls._validate_findings(findings)
        for finding in findings:
            if getattr(finding, "__pydantic_extra__", None):
                raise InvalidResearchReportError(
                    "Finding must not contain extra fields."
                )
            if not finding.supporting_chunk_ids:
                raise InvalidResearchReportError(
                    "EnhancedResearchReport findings require source provenance."
                )

    @classmethod
    def _validate_synthesized_sections(cls, sections: object) -> None:
        """Validate provenance-bearing enhanced sections without copying them."""
        if not isinstance(sections, tuple):
            raise InvalidResearchReportError(
                "EnhancedResearchReport sections must be a tuple."
            )
        for section in sections:
            if not isinstance(section, SynthesizedSection):
                raise InvalidResearchReportError(
                    "EnhancedResearchReport sections must contain "
                    "SynthesizedSection instances."
                )
            if getattr(section, "__pydantic_extra__", None):
                raise InvalidResearchReportError(
                    "SynthesizedSection must not contain extra fields."
                )
            cls._validate_string(section.heading, "SynthesizedSection heading")
            cls._validate_string(section.content, "SynthesizedSection content")
            cls._validate_chunk_ids(
                section.supporting_chunk_ids,
                "SynthesizedSection supporting_chunk_ids",
            )
            if not section.supporting_chunk_ids:
                raise InvalidResearchReportError(
                    "SynthesizedSection requires source provenance."
                )

    @classmethod
    def _validate_synthesis_metadata(cls, metadata: object) -> None:
        """Validate immutable operational metadata for enhanced reports."""
        if not isinstance(metadata, SynthesisMetadata):
            raise InvalidResearchReportError(
                "EnhancedResearchReport synthesis_metadata must be a "
                "SynthesisMetadata instance."
            )
        if getattr(metadata, "__pydantic_extra__", None):
            raise InvalidResearchReportError(
                "SynthesisMetadata must not contain extra fields."
            )
        try:
            payload = metadata.model_dump(mode="python", warnings="error")
            SynthesisMetadata.model_validate(payload)
        except (AttributeError, TypeError, ValueError) as exc:
            raise InvalidResearchReportError(
                "SynthesisMetadata failed structural validation."
            ) from exc

        cls._validate_string(metadata.provider, "SynthesisMetadata provider")
        if metadata.model is not None:
            cls._validate_string(metadata.model, "SynthesisMetadata model")
        cls._validate_optional_string(metadata.reason, "SynthesisMetadata reason")

        elapsed_ms = metadata.elapsed_ms
        if (
            isinstance(elapsed_ms, bool)
            or not isinstance(elapsed_ms, float)
            or not math.isfinite(elapsed_ms)
            or elapsed_ms < 0.0
        ):
            raise InvalidResearchReportError(
                "SynthesisMetadata elapsed_ms must be a finite non-negative float."
            )
        for field_name in ("successful", "fallback", "enhanced"):
            if not isinstance(getattr(metadata, field_name), bool):
                raise InvalidResearchReportError(
                    f"SynthesisMetadata {field_name} must be a boolean."
                )
        cls._validate_source_evidence(metadata.source_evidence)

    @classmethod
    def _validate_source_evidence(cls, values: object) -> None:
        """Validate immutable source evidence without interpreting its provider."""
        if not isinstance(values, tuple):
            raise InvalidResearchReportError(
                "SynthesisMetadata source_evidence must be a tuple."
            )

        for evidence in values:
            if not isinstance(evidence, SynthesisSourceEvidence):
                raise InvalidResearchReportError(
                    "SynthesisMetadata source_evidence must contain "
                    "SynthesisSourceEvidence instances."
                )
            if getattr(evidence, "__pydantic_extra__", None):
                raise InvalidResearchReportError(
                    "SynthesisSourceEvidence must not contain extra fields."
                )
            if not isinstance(evidence.chunk_id, UUID):
                raise InvalidResearchReportError(
                    "SynthesisSourceEvidence chunk_id must be a UUID."
                )
            if (
                isinstance(evidence.confidence, bool)
                or not isinstance(evidence.confidence, float)
                or not math.isfinite(evidence.confidence)
                or not 0.0 <= evidence.confidence <= 1.0
            ):
                raise InvalidResearchReportError(
                    "SynthesisSourceEvidence confidence must be a finite float "
                    "from 0 to 1."
                )
            cls._validate_string_collection(
                evidence.references,
                "SynthesisSourceEvidence references",
            )

    @classmethod
    def _validate_findings(cls, findings: object) -> None:
        """Validate immutable findings and their provenance IDs."""
        if not isinstance(findings, tuple):
            raise InvalidResearchReportError(
                "ResearchReport findings must be a tuple."
            )
        for finding in findings:
            if not isinstance(finding, Finding):
                raise InvalidResearchReportError(
                    "ResearchReport findings must contain Finding instances."
                )
            cls._validate_string(finding.title, "Finding title")
            cls._validate_string(finding.description, "Finding description")
            cls._validate_chunk_ids(
                finding.supporting_chunk_ids,
                "Finding supporting_chunk_ids",
            )

    @classmethod
    def _validate_timeline(cls, timeline: object) -> None:
        """Validate immutable timeline events and their provenance IDs."""
        if not isinstance(timeline, tuple):
            raise InvalidResearchReportError(
                "ResearchReport timeline must be a tuple."
            )
        for event in timeline:
            if not isinstance(event, TimelineEvent):
                raise InvalidResearchReportError(
                    "ResearchReport timeline must contain TimelineEvent instances."
                )
            cls._validate_string(event.date, "TimelineEvent date")
            cls._validate_string(event.description, "TimelineEvent description")
            cls._validate_chunk_ids(
                event.supporting_chunk_ids,
                "TimelineEvent supporting_chunk_ids",
            )

    @classmethod
    def _validate_sections(cls, sections: object) -> None:
        """Validate optional immutable extension sections."""
        if not isinstance(sections, tuple):
            raise InvalidResearchReportError(
                "ResearchReport sections must be a tuple."
            )
        for section in sections:
            if not isinstance(section, ReportSection):
                raise InvalidResearchReportError(
                    "ResearchReport sections must contain ReportSection instances."
                )
            cls._validate_string(section.heading, "ReportSection heading")
            cls._validate_string(section.content, "ReportSection content")

    @staticmethod
    def _validate_string_collection(values: object, field_name: str) -> None:
        """Validate an immutable collection of strings."""
        if not isinstance(values, tuple) or any(
            not isinstance(value, str) for value in values
        ):
            raise InvalidResearchReportError(
                f"{field_name} must be a tuple of strings."
            )

    @staticmethod
    def _validate_chunk_ids(values: object, field_name: str) -> None:
        """Validate a tuple of source-addressable chunk IDs."""
        if not isinstance(values, tuple) or any(
            not isinstance(value, UUID) for value in values
        ):
            raise InvalidResearchReportError(
                f"{field_name} must be a tuple of UUIDs."
            )

    @staticmethod
    def _validate_string(value: object, field_name: str) -> None:
        """Validate text without coercion or content normalization."""
        if not isinstance(value, str):
            raise InvalidResearchReportError(f"{field_name} must be text.")

    @staticmethod
    def _validate_optional_string(value: object, field_name: str) -> None:
        """Validate optional text without adding provider-specific semantics."""
        if value is not None and not isinstance(value, str):
            raise InvalidResearchReportError(f"{field_name} must be text or null.")
