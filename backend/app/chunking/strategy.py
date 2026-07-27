"""Pluggable span-planning strategies for deterministic text chunking."""

from abc import ABC, abstractmethod
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Iterator

from app.chunking.exceptions import InvalidChunkingConfigError
from app.chunking.utils import (
    find_forced_end,
    find_forced_end_after,
    find_overlap_boundary,
    scan_structural_groups,
    StructuralGroup,
)


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    """Immutable character-based chunking configuration."""

    max_chars: int = 3000
    overlap_chars: int = 300
    min_chunk_chars: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.max_chars, bool) or not isinstance(self.max_chars, int):
            raise InvalidChunkingConfigError("max_chars must be an integer.")
        if isinstance(self.overlap_chars, bool) or not isinstance(
            self.overlap_chars, int
        ):
            raise InvalidChunkingConfigError("overlap_chars must be an integer.")
        if self.max_chars <= 0:
            raise InvalidChunkingConfigError("max_chars must be greater than zero.")
        if self.overlap_chars < 0:
            raise InvalidChunkingConfigError("overlap_chars cannot be negative.")
        if self.overlap_chars >= self.max_chars:
            raise InvalidChunkingConfigError(
                "overlap_chars must be smaller than max_chars."
            )
        if self.min_chunk_chars is not None and (
            isinstance(self.min_chunk_chars, bool)
            or not isinstance(self.min_chunk_chars, int)
        ):
            raise InvalidChunkingConfigError("min_chunk_chars must be an integer.")
        if self.min_chunk_chars is not None and self.min_chunk_chars <= 0:
            raise InvalidChunkingConfigError(
                "min_chunk_chars must be greater than zero."
            )
        if (
            self.min_chunk_chars is not None
            and self.min_chunk_chars > self.max_chars - self.overlap_chars
        ):
            raise InvalidChunkingConfigError(
                "min_chunk_chars cannot exceed the non-overlap capacity."
            )

    @property
    def effective_min_chunk_chars(self) -> int:
        """Return the configured or deterministic default useful contribution."""
        if self.min_chunk_chars is not None:
            return self.min_chunk_chars

        return max(
            1,
            min(self.max_chars // 4, self.max_chars - self.overlap_chars),
        )


@dataclass(frozen=True, slots=True)
class ChunkSpan:
    """A source span planned by a strategy before chunk materialization."""

    start_char: int
    end_char: int


class ChunkingStrategy(ABC):
    """Interface for interchangeable character-span planning algorithms."""

    @abstractmethod
    def plan_spans(
        self,
        text: str,
        config: ChunkingConfig,
    ) -> Iterator[ChunkSpan]:
        """Yield ordered, source-addressable chunk spans for text."""


class ParagraphAwareChunkingStrategy(ChunkingStrategy):
    """Pack paragraphs, headings, and bullet lists into deterministic chunks."""

    def plan_spans(
        self,
        text: str,
        config: ChunkingConfig,
    ) -> Iterator[ChunkSpan]:
        """Yield paragraph-aware spans using linear scans and bounded fallback work."""
        groups = scan_structural_groups(text)
        hard_boundaries = self._hard_boundaries(groups, len(text))
        soft_boundaries = self._soft_boundaries(groups)
        minimum_useful_chars = config.effective_min_chunk_chars
        start = 0
        pending_span: ChunkSpan | None = None

        while start < len(text):
            previous_end = (
                pending_span.end_char if pending_span is not None else None
            )
            end = self._choose_end(
                text,
                start,
                config.max_chars,
                hard_boundaries,
                soft_boundaries,
                minimum_end=(
                    previous_end + minimum_useful_chars
                    if previous_end is not None
                    else None
                ),
            )
            if end <= start:
                end = min(len(text), start + config.max_chars)

            if previous_end is not None:
                new_contribution = end - previous_end
                if end == len(text) and new_contribution < minimum_useful_chars:
                    yield ChunkSpan(pending_span.start_char, end)
                    return

            current_span = ChunkSpan(start, end)
            if pending_span is not None:
                yield pending_span
            pending_span = current_span

            if end == len(text):
                yield pending_span
                break

            start = self._choose_next_start(
                text,
                start,
                end,
                config.overlap_chars,
                config.max_chars,
                minimum_useful_chars,
                hard_boundaries,
                soft_boundaries,
            )

    def _choose_end(
        self,
        text: str,
        start: int,
        max_chars: int,
        hard_boundaries: tuple[int, ...],
        soft_boundaries: tuple[int, ...],
        minimum_end: int | None,
    ) -> int:
        limit = min(len(text), start + max_chars)
        if limit == len(text):
            end = limit
        else:
            hard_boundary = self._rightmost_between(
                hard_boundaries,
                start,
                limit,
            )
            if hard_boundary is not None:
                end = hard_boundary
            else:
                soft_boundary = self._rightmost_between(
                    soft_boundaries,
                    start,
                    limit,
                )
                end = (
                    soft_boundary
                    if soft_boundary is not None
                    else find_forced_end(text, start, limit)
                )

        if minimum_end is None or end >= minimum_end or end == len(text):
            return end

        return self._extend_end_to_minimum(
            text,
            minimum_end,
            limit,
            hard_boundaries,
            soft_boundaries,
        )

    def _choose_next_start(
        self,
        text: str,
        current_start: int,
        end: int,
        overlap_chars: int,
        max_chars: int,
        minimum_useful_chars: int,
        hard_boundaries: tuple[int, ...],
        soft_boundaries: tuple[int, ...],
    ) -> int:
        if overlap_chars == 0:
            return end

        maximum_overlap = max_chars - minimum_useful_chars
        minimum_start = max(current_start + 1, end - maximum_overlap)
        target = max(minimum_start, end - overlap_chars)
        boundary = self._closest_boundary(
            target,
            minimum_start,
            end,
            hard_boundaries,
            soft_boundaries,
        )
        if boundary is not None:
            return boundary

        return find_overlap_boundary(text, minimum_start, end, target)

    def _extend_end_to_minimum(
        self,
        text: str,
        minimum_end: int,
        limit: int,
        hard_boundaries: tuple[int, ...],
        soft_boundaries: tuple[int, ...],
    ) -> int:
        """Extend a span until it adds the required new source content."""
        if minimum_end > limit:
            return limit

        hard_boundary = self._leftmost_between(
            hard_boundaries,
            minimum_end,
            limit,
        )
        if hard_boundary is not None:
            return hard_boundary

        soft_boundary = self._leftmost_between(
            soft_boundaries,
            minimum_end,
            limit,
        )
        if soft_boundary is not None:
            return soft_boundary

        return find_forced_end_after(text, minimum_end, limit)

    def _hard_boundaries(
        self,
        groups: tuple[StructuralGroup, ...],
        text_length: int,
    ) -> tuple[int, ...]:
        starts = [group.start for group in groups[1:]]
        return tuple(sorted({0, *starts, text_length}))

    def _soft_boundaries(
        self,
        groups: tuple[StructuralGroup, ...],
    ) -> tuple[int, ...]:
        item_starts = {
            item_start
            for group in groups
            for item_start in group.item_starts[1:]
        }
        return tuple(sorted(item_starts))

    @staticmethod
    def _rightmost_between(
        boundaries: tuple[int, ...],
        start: int,
        limit: int,
    ) -> int | None:
        index = bisect_right(boundaries, limit) - 1
        if index >= 0 and boundaries[index] > start:
            return boundaries[index]
        return None

    @staticmethod
    def _leftmost_between(
        boundaries: tuple[int, ...],
        minimum: int,
        limit: int,
    ) -> int | None:
        index = bisect_left(boundaries, minimum)
        if index < len(boundaries) and boundaries[index] <= limit:
            return boundaries[index]
        return None

    @staticmethod
    def _closest_boundary(
        target: int,
        minimum_start: int,
        end: int,
        hard_boundaries: tuple[int, ...],
        soft_boundaries: tuple[int, ...],
    ) -> int | None:
        candidates: list[int] = []
        for boundaries in (hard_boundaries, soft_boundaries):
            index = bisect_left(boundaries, target)
            for candidate_index in (index - 1, index):
                if 0 <= candidate_index < len(boundaries):
                    candidate = boundaries[candidate_index]
                    if minimum_start <= candidate < end:
                        candidates.append(candidate)

        if not candidates:
            return None

        return min(candidates, key=lambda candidate: (abs(candidate - target), candidate))
