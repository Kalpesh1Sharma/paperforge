"""Deterministic synthesis of extracted knowledge into research reports."""

import math
from uuid import UUID

from app.knowledge.models import KnowledgeObject
from app.reports.exceptions import ReportSynthesisError
from app.reports.models import Finding, ResearchReport, TimelineEvent

_KNOWLEDGE_COLLECTION_FIELDS = (
    "entities",
    "facts",
    "definitions",
    "metrics",
    "dates",
    "references",
)


class ResearchSynthesizer:
    """Build deterministic reports from validated extracted knowledge."""

    def synthesize(
        self,
        knowledge_objects: tuple[KnowledgeObject, ...],
    ) -> ResearchReport:
        """Create an immutable report while preserving source order and provenance."""
        self._validate_knowledge_objects(knowledge_objects)

        findings: list[Finding] = []
        timeline: list[TimelineEvent] = []
        entities: list[str] = []
        definitions: list[str] = []
        metrics: list[str] = []
        references: list[str] = []
        entity_values: set[str] = set()
        definition_values: set[str] = set()
        metric_values: set[str] = set()
        reference_values: set[str] = set()

        for knowledge_object in knowledge_objects:
            self._append_unique(
                knowledge_object.entities,
                entities,
                entity_values,
            )
            self._append_unique(
                knowledge_object.definitions,
                definitions,
                definition_values,
            )
            self._append_unique(
                knowledge_object.metrics,
                metrics,
                metric_values,
            )
            self._append_unique(
                knowledge_object.references,
                references,
                reference_values,
            )

            for fact in knowledge_object.facts:
                finding_number = len(findings) + 1
                findings.append(
                    Finding(
                        title=f"Finding {finding_number}",
                        description=fact,
                        supporting_chunk_ids=(knowledge_object.chunk_id,),
                    )
                )

            for date in knowledge_object.dates:
                timeline.append(
                    TimelineEvent(
                        date=date,
                        description=f"Extracted date: {date}.",
                        supporting_chunk_ids=(knowledge_object.chunk_id,),
                    )
                )

        try:
            return ResearchReport(
                title="Research Report",
                executive_summary=(
                    "Research report generated from "
                    f"{len(knowledge_objects)} extracted knowledge objects."
                ),
                findings=tuple(findings),
                important_entities=tuple(entities),
                important_definitions=tuple(definitions),
                important_metrics=tuple(metrics),
                timeline=tuple(timeline),
                references=tuple(references),
                sections=(),
            )
        except Exception as exc:
            raise ReportSynthesisError(
                "Unable to construct a research report from extracted knowledge."
            ) from exc

    @classmethod
    def _validate_knowledge_objects(cls, knowledge_objects: object) -> None:
        """Reject invalid inputs, including validation-bypassed Pydantic models."""
        if not isinstance(knowledge_objects, tuple):
            raise ReportSynthesisError(
                "Knowledge objects must be provided as a tuple."
            )

        for knowledge_object in knowledge_objects:
            cls._validate_knowledge_object(knowledge_object)

    @staticmethod
    def _validate_knowledge_object(knowledge_object: object) -> None:
        """Validate a source object without copying or mutating it."""
        if not isinstance(knowledge_object, KnowledgeObject):
            raise ReportSynthesisError(
                "Each input item must be a KnowledgeObject instance."
            )

        if getattr(knowledge_object, "__pydantic_extra__", None):
            raise ReportSynthesisError(
                "KnowledgeObject must not contain extra fields."
            )

        try:
            chunk_id = knowledge_object.chunk_id
        except AttributeError as exc:
            raise ReportSynthesisError(
                "KnowledgeObject must include a chunk_id."
            ) from exc

        if not isinstance(chunk_id, UUID):
            raise ReportSynthesisError("KnowledgeObject chunk_id must be a UUID.")

        for field_name in _KNOWLEDGE_COLLECTION_FIELDS:
            try:
                values = getattr(knowledge_object, field_name)
            except AttributeError as exc:
                raise ReportSynthesisError(
                    f"KnowledgeObject must include {field_name}."
                ) from exc

            if not isinstance(values, tuple) or any(
                not isinstance(value, str) for value in values
            ):
                raise ReportSynthesisError(
                    f"KnowledgeObject {field_name} must be a tuple of strings."
                )

        try:
            confidence = knowledge_object.confidence
        except AttributeError as exc:
            raise ReportSynthesisError(
                "KnowledgeObject must include confidence."
            ) from exc

        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, float)
            or not math.isfinite(confidence)
            or not 0.0 <= confidence <= 1.0
        ):
            raise ReportSynthesisError(
                "KnowledgeObject confidence must be a finite float from 0 to 1."
            )

    @staticmethod
    def _append_unique(
        values: tuple[str, ...],
        target: list[str],
        seen: set[str],
    ) -> None:
        """Append first-seen values while preserving their source order."""
        for value in values:
            if value not in seen:
                seen.add(value)
                target.append(value)
