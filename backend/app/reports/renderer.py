"""Deterministic Markdown rendering for research reports."""

import math
from uuid import UUID

from pydantic import ValidationError

from app.reports.enhanced_models import (
    EnhancedResearchReport,
    SynthesisMetadata,
    SynthesisSourceEvidence,
    SynthesizedSection,
)
from app.reports.exceptions import (
    InvalidResearchReportError,
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
    RenderReference,
    RenderTimelineEvent,
)


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
        """Render an immutable AI enhancement over a deterministic base report."""
        self._validate_enhanced_report(enhanced_report)

        try:
            return self._render_enhanced_report(enhanced_report)
        except InvalidResearchReportError:
            raise
        except Exception as exc:
            raise ReportRenderingError(
                "Unable to render the enhanced research report."
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
    def _render_enhanced_report(cls, enhanced_report: EnhancedResearchReport) -> str:
        """Render an enhancement overlay through one provider-agnostic context."""
        context = EnhancedReportRenderContext.from_report(enhanced_report)
        base_report = context.report.base_report
        blocks = [
            f"# {base_report.title}",
            cls._text_block("Executive Summary", context.report.executive_summary),
            cls._bullet_block(
                "Key Findings",
                cls._enhanced_finding_items(context.findings),
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
            cls._bullet_block(
                "Appendix",
                cls._enhanced_finding_items(context.appendix_findings)
                or ("No additional findings.",),
            )
        )
        return "\n\n".join(block.rstrip("\n") for block in blocks) + "\n"

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
                items.append(f"  - {item}" if group.category is not None else f"- {item}")
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
