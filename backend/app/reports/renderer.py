"""Deterministic Markdown rendering for research reports."""

from uuid import UUID

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
