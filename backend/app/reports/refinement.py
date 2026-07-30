"""Deterministic, provenance-preserving refinement for research reports."""

from dataclasses import dataclass
import re
from typing import Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.knowledge.models import KnowledgeObject
from app.reports.enhanced_models import SynthesisSourceEvidence
from app.reports.models import Finding, ResearchReport

_MAX_KEY_FINDINGS = 10
_SIMILARITY_THRESHOLD = 0.85
_MIN_SHARED_TOKENS = 3
_MAX_INDEXED_TOKEN_FREQUENCY = 64
_MAX_CANDIDATES_PER_FINDING = 128
_TOKEN_PATTERN = re.compile(r"[\w]+", flags=re.UNICODE)
_SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
_GENERIC_TITLE_PATTERN = re.compile(r"^finding(?:\s+\d+)?$", flags=re.IGNORECASE)
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)


class InvalidRefinementRewriteError(ValueError):
    """Raised when an AI rewrite changes a canonical finding's provenance."""


class CandidateRewrite(BaseModel):
    """A validated AI wording update for one deterministic candidate."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    candidate_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    supporting_chunk_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("candidate_id", "title", "description")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        """Reject whitespace-only AI wording without changing it."""
        if not value.strip():
            raise ValueError("Refinement rewrite text must not be blank.")
        return value


@dataclass(frozen=True)
class RefinementCandidate:
    """A ranked canonical finding that an AI may reword but not redefine."""

    candidate_id: str
    finding: Finding
    original_index: int


@dataclass(frozen=True)
class RefinementPlan:
    """Immutable deterministic inputs and outputs for document refinement."""

    executive_summary: str
    source_evidence: tuple[SynthesisSourceEvidence, ...]
    candidates: tuple[RefinementCandidate, ...]
    findings: tuple[Finding, ...]
    appendix_findings: tuple[Finding, ...]


@dataclass(frozen=True)
class _PreparedFinding:
    """Cached lexical form of a finding used during bounded merge planning."""

    original_index: int
    finding: Finding
    normalized_description: str
    content_tokens: frozenset[str]


@dataclass
class _FindingGroup:
    """Mutable construction state that is converted into immutable candidates."""

    first_index: int
    members: list[_PreparedFinding]
    representative_tokens: frozenset[str]


class ReportRefiner:
    """Create stable, conservative report improvements without AI or I/O."""

    @classmethod
    def build_plan(
        cls,
        report: ResearchReport,
        knowledge_objects: tuple[KnowledgeObject, ...],
    ) -> RefinementPlan:
        """Build canonical candidates, a fallback summary, and source evidence."""
        knowledge_by_id = {
            knowledge_object.chunk_id: knowledge_object
            for knowledge_object in knowledge_objects
        }
        prepared = tuple(
            cls._prepare_finding(index, finding)
            for index, finding in enumerate(report.findings)
        )
        groups = cls._group_findings(prepared)
        candidates = tuple(
            cls._candidate_from_group(group, knowledge_by_id)
            for group in groups
        )
        ranked_candidates = tuple(
            sorted(
                candidates,
                key=lambda candidate: cls._ranking_key(
                    candidate,
                    knowledge_by_id,
                ),
            )
        )
        findings, appendix_findings = cls._split_findings(ranked_candidates)
        return RefinementPlan(
            executive_summary=cls._build_summary(
                report,
                findings + appendix_findings,
            ),
            source_evidence=tuple(
                SynthesisSourceEvidence(
                    chunk_id=knowledge_object.chunk_id,
                    confidence=knowledge_object.confidence,
                    references=knowledge_object.references,
                )
                for knowledge_object in knowledge_objects
            ),
            candidates=ranked_candidates,
            findings=findings,
            appendix_findings=appendix_findings,
        )

    @classmethod
    def apply_rewrites(
        cls,
        plan: RefinementPlan,
        rewrites: tuple[CandidateRewrite, ...],
    ) -> tuple[tuple[Finding, ...], tuple[Finding, ...]]:
        """Apply only exact-provenance AI wording changes to canonical findings."""
        candidate_by_id = {
            candidate.candidate_id: candidate for candidate in plan.candidates
        }
        rewrite_by_id: dict[str, CandidateRewrite] = {}
        for rewrite in rewrites:
            if rewrite.candidate_id in rewrite_by_id:
                raise InvalidRefinementRewriteError(
                    "A refinement candidate may be rewritten at most once."
                )
            candidate = candidate_by_id.get(rewrite.candidate_id)
            if candidate is None:
                raise InvalidRefinementRewriteError(
                    "A refinement rewrite referenced an unknown candidate."
                )
            if rewrite.supporting_chunk_ids != candidate.finding.supporting_chunk_ids:
                raise InvalidRefinementRewriteError(
                    "A refinement rewrite changed canonical source provenance."
                )
            rewrite_by_id[rewrite.candidate_id] = rewrite

        rewritten_candidates = tuple(
            RefinementCandidate(
                candidate_id=candidate.candidate_id,
                finding=cls._rewritten_finding(
                    candidate.finding,
                    rewrite_by_id.get(candidate.candidate_id),
                ),
                original_index=candidate.original_index,
            )
            for candidate in plan.candidates
        )
        return cls._split_findings(rewritten_candidates)

    @staticmethod
    def _rewritten_finding(
        finding: Finding,
        rewrite: CandidateRewrite | None,
    ) -> Finding:
        """Reuse canonical content when the model omitted a safe rewrite."""
        if rewrite is None:
            return finding
        return Finding(
            title=rewrite.title,
            description=rewrite.description,
            supporting_chunk_ids=finding.supporting_chunk_ids,
        )

    @staticmethod
    def _split_findings(
        candidates: tuple[RefinementCandidate, ...],
    ) -> tuple[tuple[Finding, ...], tuple[Finding, ...]]:
        """Partition the ranked list into primary and appendix findings."""
        findings = tuple(candidate.finding for candidate in candidates)
        return findings[:_MAX_KEY_FINDINGS], findings[_MAX_KEY_FINDINGS:]

    @classmethod
    def _prepare_finding(
        cls,
        original_index: int,
        finding: Finding,
    ) -> _PreparedFinding:
        """Cache the normalized text representation needed for matching."""
        normalized_description = cls._normalize(finding.description)
        tokens = frozenset(
            token
            for token in cls._tokens(finding.description)
            if token not in _STOP_WORDS
        )
        return _PreparedFinding(
            original_index=original_index,
            finding=finding,
            normalized_description=normalized_description,
            content_tokens=tokens,
        )

    @classmethod
    def _group_findings(
        cls,
        prepared: tuple[_PreparedFinding, ...],
    ) -> tuple[_FindingGroup, ...]:
        """Merge exact and bounded high-overlap lexical duplicate candidates."""
        token_frequency = cls._token_frequency(prepared)
        groups: list[_FindingGroup] = []
        exact_index: dict[str, int] = {}
        inverted_index: dict[str, list[int]] = {}

        for item in prepared:
            exact_group_index = exact_index.get(item.normalized_description)
            if exact_group_index is not None:
                groups[exact_group_index].members.append(item)
                continue

            candidate_indexes = cls._candidate_group_indexes(
                item,
                token_frequency,
                inverted_index,
            )
            matching_group_index = next(
                (
                    group_index
                    for group_index in candidate_indexes
                    if cls._is_conservative_duplicate(
                        item.content_tokens,
                        groups[group_index].representative_tokens,
                    )
                ),
                None,
            )
            if matching_group_index is None:
                matching_group_index = len(groups)
                groups.append(
                    _FindingGroup(
                        first_index=item.original_index,
                        members=[item],
                        representative_tokens=item.content_tokens,
                    )
                )
            else:
                groups[matching_group_index].members.append(item)

            exact_index[item.normalized_description] = matching_group_index
            cls._index_item_tokens(
                item,
                matching_group_index,
                token_frequency,
                inverted_index,
            )

        return tuple(groups)

    @staticmethod
    def _token_frequency(
        prepared: tuple[_PreparedFinding, ...],
    ) -> dict[str, int]:
        """Count tokens once so common terms do not create broad candidate sets."""
        frequency: dict[str, int] = {}
        for item in prepared:
            for token in item.content_tokens:
                frequency[token] = frequency.get(token, 0) + 1
        return frequency

    @staticmethod
    def _candidate_group_indexes(
        item: _PreparedFinding,
        token_frequency: dict[str, int],
        inverted_index: dict[str, list[int]],
    ) -> tuple[int, ...]:
        """Return bounded, deterministic lexical merge candidates."""
        candidates: set[int] = set()
        for token in sorted(item.content_tokens):
            if token_frequency.get(token, 0) > _MAX_INDEXED_TOKEN_FREQUENCY:
                continue
            candidates.update(inverted_index.get(token, ()))
            if len(candidates) >= _MAX_CANDIDATES_PER_FINDING:
                break
        return tuple(sorted(candidates)[:_MAX_CANDIDATES_PER_FINDING])

    @staticmethod
    def _index_item_tokens(
        item: _PreparedFinding,
        group_index: int,
        token_frequency: dict[str, int],
        inverted_index: dict[str, list[int]],
    ) -> None:
        """Index only bounded-frequency terms without duplicate group entries."""
        for token in item.content_tokens:
            if token_frequency.get(token, 0) > _MAX_INDEXED_TOKEN_FREQUENCY:
                continue
            group_indexes = inverted_index.setdefault(token, [])
            if not group_indexes or group_indexes[-1] != group_index:
                group_indexes.append(group_index)

    @staticmethod
    def _is_conservative_duplicate(
        left: frozenset[str],
        right: frozenset[str],
    ) -> bool:
        """Require high content-token overlap before merging non-exact text."""
        shared_count = len(left.intersection(right))
        if shared_count < _MIN_SHARED_TOKENS:
            return False
        union_count = len(left.union(right))
        return union_count > 0 and shared_count / union_count >= _SIMILARITY_THRESHOLD

    @classmethod
    def _candidate_from_group(
        cls,
        group: _FindingGroup,
        knowledge_by_id: dict[UUID, KnowledgeObject],
    ) -> RefinementCandidate:
        """Create one immutable canonical finding from a merged source group."""
        best_member = min(
            group.members,
            key=lambda member: cls._member_quality_key(member, knowledge_by_id),
        )
        supporting_chunk_ids = cls._ordered_chunk_ids(group.members)
        title = best_member.finding.title
        if _GENERIC_TITLE_PATTERN.fullmatch(title.strip()):
            title = cls._title_from_description(
                best_member.finding.description,
                group.first_index,
            )
        return RefinementCandidate(
            candidate_id=f"finding-{group.first_index + 1:04d}",
            finding=Finding(
                title=title,
                description=best_member.finding.description,
                supporting_chunk_ids=supporting_chunk_ids,
            ),
            original_index=group.first_index,
        )

    @staticmethod
    def _ordered_chunk_ids(
        members: Iterable[_PreparedFinding],
    ) -> tuple[UUID, ...]:
        """Combine source UUIDs in first-seen order without duplicates."""
        ordered: list[UUID] = []
        seen: set[UUID] = set()
        for member in members:
            for chunk_id in member.finding.supporting_chunk_ids:
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    ordered.append(chunk_id)
        return tuple(ordered)

    @classmethod
    def _member_quality_key(
        cls,
        member: _PreparedFinding,
        knowledge_by_id: dict[UUID, KnowledgeObject],
    ) -> tuple[float, int, int]:
        """Sort quality by confidence, explanation richness, then source order."""
        confidence = cls._max_confidence(
            member.finding.supporting_chunk_ids,
            knowledge_by_id,
        )
        return -confidence, -len(member.finding.description), member.original_index

    @classmethod
    def _ranking_key(
        cls,
        candidate: RefinementCandidate,
        knowledge_by_id: dict[UUID, KnowledgeObject],
    ) -> tuple[float, float, int, int, int, int, int, int]:
        """Return a stable descending multi-signal importance sort key."""
        sources = tuple(
            knowledge_by_id[chunk_id]
            for chunk_id in candidate.finding.supporting_chunk_ids
            if chunk_id in knowledge_by_id
        )
        confidences = tuple(source.confidence for source in sources)
        max_confidence = max(confidences, default=0.0)
        mean_confidence = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )
        has_metrics = int(any(source.metrics for source in sources))
        has_dates = int(any(source.dates for source in sources))
        entity_count = sum(len(source.entities) for source in sources)
        definition_count = sum(len(source.definitions) for source in sources)
        return (
            -max_confidence,
            -mean_confidence,
            -len(candidate.finding.supporting_chunk_ids),
            -has_metrics,
            -has_dates,
            -entity_count,
            -definition_count,
            candidate.original_index,
        )

    @staticmethod
    def _max_confidence(
        chunk_ids: tuple[UUID, ...],
        knowledge_by_id: dict[UUID, KnowledgeObject],
    ) -> float:
        """Return the strongest available source confidence for one finding."""
        return max(
            (
                knowledge_by_id[chunk_id].confidence
                for chunk_id in chunk_ids
                if chunk_id in knowledge_by_id
            ),
            default=0.0,
        )

    @classmethod
    def _build_summary(
        cls,
        report: ResearchReport,
        findings: tuple[Finding, ...],
    ) -> str:
        """Build concise factual fallback prose without an object-count placeholder."""
        paragraphs: list[str] = []
        entities = report.important_entities[:4]
        if entities:
            paragraphs.append(
                "The document focuses on " + cls._human_list(entities) + "."
            )
        elif findings:
            paragraphs.append(
                "The document presents evidence about "
                f"{findings[0].title.lower()}."
            )

        if findings:
            descriptions = tuple(
                cls._sentence_fragment(finding.description)
                for finding in findings[:2]
            )
            paragraphs.append(
                "Key extracted findings include "
                + cls._human_list(descriptions)
                + "."
            )

        metric_or_timeline_parts: list[str] = []
        if report.important_metrics:
            metric_or_timeline_parts.append(
                "Reported metrics include "
                + cls._human_list(
                    tuple(
                        cls._sentence_fragment(metric)
                        for metric in report.important_metrics[:3]
                    )
                )
                + "."
            )
        if report.timeline:
            metric_or_timeline_parts.append(
                "The extracted chronology includes "
                + cls._human_list(
                    tuple(
                        cls._sentence_fragment(event.date)
                        for event in report.timeline[:3]
                    )
                )
                + "."
            )
        if metric_or_timeline_parts:
            paragraphs.append(" ".join(metric_or_timeline_parts))

        if report.important_definitions:
            paragraphs.append(
                "Defined concepts include "
                + cls._human_list(
                    tuple(
                        cls._sentence_fragment(definition)
                        for definition in report.important_definitions[:2]
                    )
                )
                + "."
            )

        if not paragraphs:
            return "No factual content was extracted from the supplied knowledge objects."
        return "\n\n".join(paragraphs[:4])

    @staticmethod
    def _title_from_description(description: str, original_index: int) -> str:
        """Use the first source sentence as a non-invented readable title."""
        sentence = _SENTENCE_PATTERN.split(description.strip(), maxsplit=1)[0]
        sentence = sentence.rstrip(".?! ")
        if not sentence:
            return f"Finding {original_index + 1}"
        if len(sentence) <= 80:
            return sentence
        truncated = sentence[:80].rsplit(" ", maxsplit=1)[0].rstrip()
        return truncated or sentence[:80].rstrip()

    @staticmethod
    def _sentence_fragment(value: str) -> str:
        """Use source wording in generated prose without doubled punctuation."""
        return value.rstrip().rstrip(".?!")

    @staticmethod
    def _normalize(value: str) -> str:
        """Return a case-folded lexical normalization without text generation."""
        return " ".join(ReportRefiner._tokens(value))

    @staticmethod
    def _tokens(value: str) -> tuple[str, ...]:
        """Extract deterministic lowercase lexical tokens while retaining numbers."""
        return tuple(match.group(0).casefold() for match in _TOKEN_PATTERN.finditer(value))

    @staticmethod
    def _human_list(values: tuple[str, ...]) -> str:
        """Join source strings into concise deterministic prose."""
        if len(values) == 1:
            return values[0]
        if len(values) == 2:
            return f"{values[0]} and {values[1]}"
        return ", ".join(values[:-1]) + f", and {values[-1]}"
