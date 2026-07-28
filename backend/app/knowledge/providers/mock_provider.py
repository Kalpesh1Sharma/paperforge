"""Deterministic rule-based knowledge provider for architecture validation."""

import re
from collections.abc import Iterable

from app.knowledge.models import KnowledgeObject
from app.knowledge.providers.base import BaseKnowledgeProvider
from app.models.document_chunk import DocumentChunk

_TITLE_CASE_WORD = r"[A-Z][a-z]+(?:[''][A-Z][a-z]+)?(?:-[A-Z][a-z]+)*"
_TITLE_CASE_ENTITY_PATTERN = re.compile(
    rf"(?<![\w'-]){_TITLE_CASE_WORD}(?:\s+{_TITLE_CASE_WORD})+(?![\w'-])"
)
_ALL_CAPS_ENTITY_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:[A-Z]{2,}(?:-[A-Z]{2,})?)(?![A-Z0-9])"
)
_MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|"
    "October|November|December"
)
_YEAR_PATTERN = r"(?:1[5-9]\d{2}|2[01]\d{2})"
_DATE_PATTERN = re.compile(
    rf"(?<!\d)\d{{4}}-\d{{2}}-\d{{2}}(?!\d)|"
    rf"\b(?:{_MONTH_NAMES})\s+{_YEAR_PATTERN}\b|"
    rf"(?<![\d-]){_YEAR_PATTERN}(?![\d-])",
    re.IGNORECASE,
)
_MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]\r\n]+\]\([^\s()]+\)")
_RAW_URL_PATTERN = re.compile(r"https?://[^\s<>\]\)]+(?<![.,;:!?])")
_NUMBER_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_UNIT_PATTERN = (
    r"(?:kg|g|mg|km|m|cm|mm|mi|ft|lb|lbs|oz|ml|l|ms|s|min|h|hr|hrs|"
    r"hz|khz|mhz|ghz|kb|mb|gb|tb)"
)
_METRIC_PATTERN = re.compile(
    rf"(?<![\w.])(?:\${_NUMBER_PATTERN}|{_NUMBER_PATTERN}%|"
    rf"{_NUMBER_PATTERN}\s+{_UNIT_PATTERN}\b|{_NUMBER_PATTERN})(?!\w)",
    re.IGNORECASE,
)
_DEFINITION_PATTERN = re.compile(
    r"^\s*.+?\s+(?:is|refers\s+to|means)\s+.+?\.\s*$",
    re.IGNORECASE,
)


class MockKnowledgeProvider(BaseKnowledgeProvider):
    """Extract predictable rule-based knowledge without external dependencies."""

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        """Return deterministic knowledge extracted from one document chunk."""
        reference_matches = self._reference_matches(chunk.text)
        reference_spans = tuple(match.span() for match in reference_matches)
        date_matches = tuple(
            match
            for match in _DATE_PATTERN.finditer(chunk.text)
            if not self._overlaps_any(match.span(), reference_spans)
        )
        reserved_spans = self._merge_spans(
            [
                *(match.span() for match in date_matches),
                *reference_spans,
            ]
        )

        return KnowledgeObject(
            chunk_id=chunk.chunk_id,
            entities=self._entities(chunk.text),
            facts=self._facts(chunk.text),
            definitions=self._definitions(chunk.text),
            metrics=self._metrics(chunk.text, reserved_spans),
            dates=tuple(match.group(0) for match in date_matches),
            references=tuple(match.group(0) for match in reference_matches),
            confidence=1.0,
        )

    @staticmethod
    def _entities(text: str) -> tuple[str, ...]:
        candidates = [
            *(
                (match.start(), match.end(), match.group(0))
                for match in _TITLE_CASE_ENTITY_PATTERN.finditer(text)
            ),
            *(
                (match.start(), match.end(), match.group(0))
                for match in _ALL_CAPS_ENTITY_PATTERN.finditer(text)
            ),
        ]
        candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))

        entities: list[str] = []
        seen: set[str] = set()
        for _, _, entity in candidates:
            if entity not in seen:
                seen.add(entity)
                entities.append(entity)

        return tuple(entities)

    @staticmethod
    def _facts(text: str) -> tuple[str, ...]:
        facts: list[str] = []
        for _, _, sentence in MockKnowledgeProvider._sentences(text):
            if MockKnowledgeProvider._word_count(sentence) >= 3:
                facts.append(sentence)

        return tuple(facts)

    @staticmethod
    def _definitions(text: str) -> tuple[str, ...]:
        return tuple(
            sentence
            for _, _, sentence in MockKnowledgeProvider._sentences(text)
            if _DEFINITION_PATTERN.fullmatch(sentence)
        )

    @staticmethod
    def _metrics(
        text: str,
        reserved_spans: tuple[tuple[int, int], ...],
    ) -> tuple[str, ...]:
        metrics: list[str] = []
        reserved_index = 0

        for match in _METRIC_PATTERN.finditer(text):
            start, end = match.span()
            while (
                reserved_index < len(reserved_spans)
                and reserved_spans[reserved_index][1] <= start
            ):
                reserved_index += 1
            if (
                reserved_index < len(reserved_spans)
                and reserved_spans[reserved_index][0] < end
            ):
                continue
            metrics.append(match.group(0))

        return tuple(metrics)

    @staticmethod
    def _reference_matches(text: str) -> tuple[re.Match[str], ...]:
        markdown_matches = tuple(_MARKDOWN_LINK_PATTERN.finditer(text))
        markdown_spans = tuple(match.span() for match in markdown_matches)
        raw_matches = tuple(
            match
            for match in _RAW_URL_PATTERN.finditer(text)
            if not MockKnowledgeProvider._overlaps_any(match.span(), markdown_spans)
        )

        return tuple(
            sorted(
                (*markdown_matches, *raw_matches),
                key=lambda match: (match.start(), match.end()),
            )
        )

    @staticmethod
    def _sentences(text: str) -> Iterable[tuple[int, int, str]]:
        start = 0
        for index, character in enumerate(text):
            if character != ".":
                continue
            if index + 1 < len(text) and not text[index + 1].isspace():
                continue

            sentence = text[start : index + 1].strip()
            if sentence:
                yield start, index + 1, sentence
            start = index + 1

    @staticmethod
    def _word_count(text: str) -> int:
        word_count = 0
        in_word = False

        for character in text:
            if character.isspace():
                in_word = False
            elif not in_word:
                word_count += 1
                in_word = True

        return word_count

    @staticmethod
    def _merge_spans(
        spans: Iterable[tuple[int, int]],
    ) -> tuple[tuple[int, int], ...]:
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                previous_start, previous_end = merged[-1]
                merged[-1] = (previous_start, max(previous_end, end))
            else:
                merged.append((start, end))

        return tuple(merged)

    @staticmethod
    def _overlaps_any(
        span: tuple[int, int],
        other_spans: Iterable[tuple[int, int]],
    ) -> bool:
        start, end = span
        return any(
            start < other_end and other_start < end
            for other_start, other_end in other_spans
        )
