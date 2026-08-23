"""Render-only deterministic source labels for enhanced research reports."""

from dataclasses import dataclass
from uuid import UUID

from app.reports.enhanced_models import EnhancedResearchReport


@dataclass(frozen=True)
class CitationSource:
    """One human-readable source label and its extracted references."""

    label: str
    references: tuple[str, ...]


class CitationIndex:
    """Map internal chunk identifiers to deterministic ``Source N`` labels."""

    def __init__(
        self,
        labels: dict[UUID, str],
        sources: tuple[CitationSource, ...],
    ) -> None:
        """Store render-only mappings without modifying the source report."""
        self._labels = labels
        self._sources = sources

    @classmethod
    def from_report(
        cls,
        report: EnhancedResearchReport,
        source_filename: str | None = None,
    ) -> "CitationIndex":
        """Build labels from evidence order, using source context when available."""
        labels: dict[UUID, str] = {}
        sources: list[CitationSource] = []
        has_source_evidence = bool(report.synthesis_metadata.source_evidence)
        label_prefix = (
            source_filename.strip()
            if isinstance(source_filename, str) and source_filename.strip()
            else None
        )

        for evidence in report.synthesis_metadata.source_evidence:
            if evidence.chunk_id in labels:
                continue
            label = cls._next_label(labels, label_prefix)
            labels[evidence.chunk_id] = label
            sources.append(CitationSource(label, evidence.references))

        for chunk_id in cls._referenced_chunk_ids(report):
            if chunk_id not in labels:
                label = cls._next_label(labels, label_prefix)
                labels[chunk_id] = label
                sources.append(CitationSource(label, ()))

        if not has_source_evidence:
            cls._attach_legacy_references(sources, report.base_report.references)

        if not sources:
            for reference in report.base_report.references:
                label = f"Source {len(sources) + 1}"
                sources.append(CitationSource(label, (reference,)))

        return cls(labels, tuple(sources))

    @property
    def sources(self) -> tuple[CitationSource, ...]:
        """Return source entries in their deterministic display order."""
        return self._sources

    @property
    def labels(self) -> dict[UUID, str]:
        """Expose a copy-free mapping for HTML template lookup."""
        return self._labels

    def labels_for(self, chunk_ids: tuple[UUID, ...]) -> tuple[str, ...]:
        """Return exact human labels for one provenance-bearing statement."""
        return tuple(self._labels[chunk_id] for chunk_id in chunk_ids)

    @staticmethod
    def _next_label(labels: dict[UUID, str], source_filename: str | None) -> str:
        """Return the next stable one-based source label."""
        position = len(labels) + 1
        if source_filename is not None:
            return f"{source_filename} · excerpt {position}"
        return f"Source {position}"

    @staticmethod
    def _attach_legacy_references(
        sources: list[CitationSource],
        references: tuple[str, ...],
    ) -> None:
        """Retain legacy report references when no chunk evidence was stored."""
        for index, reference in enumerate(references):
            if index < len(sources):
                source = sources[index]
                sources[index] = CitationSource(
                    source.label,
                    source.references + (reference,),
                )
            else:
                sources.append(
                    CitationSource(
                        f"Source {len(sources) + 1}",
                        (reference,),
                    )
                )

    @staticmethod
    def _referenced_chunk_ids(
        report: EnhancedResearchReport,
    ) -> tuple[UUID, ...]:
        """Collect chunk IDs in the report's eventual display order."""
        ordered: list[UUID] = []
        seen: set[UUID] = set()

        def append(chunk_ids: tuple[UUID, ...]) -> None:
            for chunk_id in chunk_ids:
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    ordered.append(chunk_id)

        for finding in report.findings:
            append(finding.supporting_chunk_ids)
        for event in report.base_report.timeline:
            append(event.supporting_chunk_ids)
        for section in report.sections:
            append(section.supporting_chunk_ids)
        for finding in report.appendix_findings:
            append(finding.supporting_chunk_ids)

        intelligence = report.report_intelligence
        if intelligence is not None:
            for finding in intelligence.findings:
                append(finding.supporting_chunk_ids)
            for definition in intelligence.definitions:
                append(definition.supporting_chunk_ids)
            for event in intelligence.timeline:
                append(event.supporting_chunk_ids)
            for reference in intelligence.references:
                append(reference.supporting_chunk_ids)
            for group in intelligence.entity_groups:
                for entity in group.entities:
                    append(entity.supporting_chunk_ids)

        return tuple(ordered)
