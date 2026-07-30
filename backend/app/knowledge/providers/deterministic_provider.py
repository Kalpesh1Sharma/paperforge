"""Deterministic local knowledge extraction for provider-fallback workflows."""

from app.knowledge.models import KnowledgeObject
from app.knowledge.providers.base import BaseKnowledgeProvider
from app.knowledge.providers.mock_provider import _DATE_PATTERN, MockKnowledgeProvider
from app.models.document_chunk import DocumentChunk


class DeterministicKnowledgeProvider(BaseKnowledgeProvider):
    """Extract conservative, source-backed knowledge without external services.

    This provider deliberately reuses the established rule-based matching helpers
    from :class:`MockKnowledgeProvider` while assigning a lower confidence range
    appropriate for deterministic fallback extraction.
    """

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        """Return immutable local knowledge for ``chunk`` in source order."""
        reference_matches = MockKnowledgeProvider._reference_matches(chunk.text)
        reference_spans = tuple(match.span() for match in reference_matches)
        date_matches = tuple(
            match
            for match in _DATE_PATTERN.finditer(chunk.text)
            if not MockKnowledgeProvider._overlaps_any(match.span(), reference_spans)
        )
        reserved_spans = MockKnowledgeProvider._merge_spans(
            [
                *(match.span() for match in date_matches),
                *reference_spans,
            ]
        )

        entities = self._stable_unique(MockKnowledgeProvider._entities(chunk.text))
        facts = MockKnowledgeProvider._facts(chunk.text)
        definitions = MockKnowledgeProvider._definitions(chunk.text)
        metrics = MockKnowledgeProvider._metrics(chunk.text, reserved_spans)
        dates = tuple(match.group(0) for match in date_matches)
        references = self._stable_unique(
            tuple(match.group(0) for match in reference_matches)
        )

        populated_category_count = sum(
            bool(values)
            for values in (
                entities,
                facts,
                definitions,
                metrics,
                dates,
                references,
            )
        )

        return KnowledgeObject(
            chunk_id=chunk.chunk_id,
            entities=entities,
            facts=facts,
            definitions=definitions,
            metrics=metrics,
            dates=dates,
            references=references,
            confidence=self._confidence(populated_category_count),
        )

    @staticmethod
    def _stable_unique(values: tuple[str, ...]) -> tuple[str, ...]:
        """Keep the first exact occurrence of each value in source order."""
        seen: set[str] = set()
        unique_values: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            unique_values.append(value)
        return tuple(unique_values)

    @staticmethod
    def _confidence(populated_category_count: int) -> float:
        """Map populated categories into the conservative 0.45--0.70 range."""
        category_total = 6
        bounded_count = max(0, min(populated_category_count, category_total))
        return round(0.45 + (0.25 * bounded_count / category_total), 4)
