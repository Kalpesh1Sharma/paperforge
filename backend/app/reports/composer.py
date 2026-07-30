"""Deterministic composition of enhanced reports into presentation models.

``ReportComposer`` is an in-process adapter between the immutable report
pipeline and presentation renderers.  It performs no provider work, does not
read the clock, and never changes any canonical report object.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Iterable, TypeVar
from uuid import UUID

from pydantic import ValidationError

from app.models.parsed_document import ParsedDocument
from app.reports.enhanced_models import EnhancedResearchReport
from app.reports.exceptions import (
    InvalidResearchReportError,
    ReportCompositionError,
)
from app.reports.presentation import (
    EnhancedReportRenderContext,
    RenderDefinition,
    RenderEntity,
    RenderFinding,
    RenderReference,
    RenderTimelineEvent,
)
from app.reports.presentation_models import (
    AppendixGroup,
    CompressionStatistic,
    ConceptCard,
    DocumentMetadata,
    EntityCard,
    EntityPresentationGroup,
    EvidenceTable,
    GroupedFinding,
    HiddenPresentationData,
    InsightCard,
    MetricCard,
    PRESENTATION_SECTION_SPECS,
    PresentationBudget,
    PresentationEvidence,
    PresentationModel,
    PresentationSection,
    ReferenceCard,
    ReportMode,
    TableOfContents,
    TableOfContentsEntry,
    TimelineCard,
)

_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n\s*\n+")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+#/.-]+")
_SPACE_PATTERN = re.compile(r"\s+")
_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
_NUMBERED_HEADING_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)+(?:[.)])?\s+.+$")
_RAW_ENUMERATION_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s*$")
_PAGE_ARTIFACT_PATTERN = re.compile(
    r"^\s*(?:page|section|chapter|table|figure)\s+\d+(?:\s+\d+)?\s*$",
    flags=re.IGNORECASE,
)
_PAGE_COUNT_STATEMENT_PATTERN = re.compile(
    r"\b(?:page\s+count|total\s+pages?)\s*(?:is|:|=|of)?\s*\d+"
    r"|\b(?:document|report|file)\s+(?:contains|contain|has|have)\s+\d+\s+pages?\b",
    flags=re.IGNORECASE,
)
_LABELED_METRIC_PATTERN = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9 /()#._-]{1,80}?)\s*(?::|=|[-—])\s*(\S(?:.*\S)?)\s*$"
)

_IMPORTANCE_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
_PRIMARY_FINDING_HEADING = "Principal Findings"
_TECHNICAL_THEME_ORDER = (
    "Architecture",
    "Standards",
    "Security",
    "Performance",
    "Accessibility",
    "Libraries",
    "Formats",
    "General",
)
_TECHNICAL_THEME_TERMS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "Architecture",
        frozenset(
            {
                "architecture",
                "pipeline",
                "component",
                "components",
                "system",
                "integration",
                "api",
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
                "specification",
                "compliance",
                "approved",
                "adopted",
            }
        ),
    ),
    (
        "Security",
        frozenset(
            {"security", "secure", "encryption", "signature", "privacy"}
        ),
    ),
    (
        "Performance",
        frozenset({"performance", "latency", "throughput", "speed", "efficient"}),
    ),
    (
        "Accessibility",
        frozenset({"accessibility", "accessible", "screen", "reader", "wcag"}),
    ),
    (
        "Libraries",
        frozenset({"library", "libraries", "package", "packages", "dependency"}),
    ),
    (
        "Formats",
        frozenset({"format", "formats", "pdf", "docx", "markdown", "file"}),
    ),
)
_DOMAIN_ORDER = (
    "Document Technology & Standards",
    "Software Engineering",
    "Security & Compliance",
    "Accessibility",
    "General Research",
)
_DOMAIN_CATEGORY_SCORES = {
    "Standards": "Document Technology & Standards",
    "Technologies": "Document Technology & Standards",
    "File Formats": "Document Technology & Standards",
    "Programming Languages": "Software Engineering",
    "Libraries": "Software Engineering",
    "Security": "Security & Compliance",
    "Accessibility": "Accessibility",
}
_DOMAIN_THEME_SCORES = {
    "Architecture": "Software Engineering",
    "Standards": "Document Technology & Standards",
    "Security": "Security & Compliance",
    "Performance": "Software Engineering",
    "Accessibility": "Accessibility",
    "Libraries": "Software Engineering",
    "Formats": "Document Technology & Standards",
    "General": "General Research",
}

_STOP_TOKENS = frozenset(
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
_EVENT_VERBS = frozenset(
    {
        "adopt",
        "adopted",
        "announce",
        "announced",
        "approve",
        "approved",
        "establish",
        "established",
        "introduce",
        "introduced",
        "launch",
        "launched",
        "publish",
        "published",
        "release",
        "released",
        "standardize",
        "standardized",
    }
)
_LAYOUT_OBSERVATION_TOKENS = frozenset(
    {
        "chapter",
        "chapters",
        "font",
        "fonts",
        "heading",
        "headings",
        "layout",
        "margin",
        "margins",
        "numbering",
        "page",
        "pages",
        "paragraph",
        "paragraphs",
        "spacing",
        "style",
        "styles",
        "table",
        "tables",
        "typeface",
    }
)
_LAYOUT_CONTEXT_TOKENS = frozenset(
    {
        "contains",
        "document",
        "has",
        "includes",
        "records",
        "report",
        "shows",
        "uses",
    }
)
_SUBSTANTIVE_FINDING_TOKENS = frozenset(
    {
        "algorithm",
        "architecture",
        "compliance",
        "encryption",
        "interoperability",
        "performance",
        "security",
        "standard",
        "standards",
        "workflow",
    }
)
_T = TypeVar("_T")


@dataclass(frozen=True)
class _FindingCandidate:
    """Private ranking data for an authoritative primary finding."""

    source_index: int
    card: InsightCard
    raw_confidence: float | None
    is_canonical: bool = True
    is_appendix: bool = False

    @property
    def sort_key(self) -> tuple[int, float, int, int]:
        """Return the fixed selection ordering for key insights."""
        return (
            -_IMPORTANCE_RANK.get(self.card.importance or "", 0),
            -(self.raw_confidence if self.raw_confidence is not None else -1.0),
            -self.card.evidence.source_count,
            self.source_index,
        )


@dataclass(frozen=True)
class _ConceptCandidate:
    """Private deterministic ranking data for a definition card."""

    source_index: int
    card: ConceptCard
    raw_confidence: float | None

    @property
    def sort_key(self) -> tuple[float, int, int, int]:
        """Prefer source confidence, support, citations, then source order."""
        return (
            -(self.raw_confidence if self.raw_confidence is not None else -1.0),
            -self.card.evidence.source_count,
            -len(self.card.evidence.references),
            self.source_index,
        )


@dataclass(frozen=True)
class _CurationResult:
    """Private, immutable output of one deterministic curation pass."""

    cards: tuple
    deduplicated: int
    artifact_rejected: int


@dataclass(frozen=True)
class _MetricCurationResult:
    """Private metric curation that preserves bare source values off-page."""

    cards: tuple[MetricCard, ...]
    unlabeled_values: tuple[str, ...]
    deduplicated: int
    artifact_rejected: int


@dataclass(frozen=True)
class _ReferenceCurationResult:
    """Private reference consolidation with deterministic merge accounting."""

    cards: tuple[ReferenceCard, ...]
    extracted: int
    deduplicated: int


@dataclass(frozen=True)
class _EntityCurationResult:
    """Private entity allocation and parser-residue accounting."""

    visible_groups: tuple[EntityPresentationGroup, ...]
    hidden_groups: tuple[EntityPresentationGroup, ...]
    extracted: int
    deduplicated: int
    artifact_rejected: int


class ReportComposer:
    """Compose an immutable renderer-ready report without provider calls."""

    def __init__(
        self,
        mode: ReportMode = ReportMode.PROFESSIONAL,
        budget: PresentationBudget | None = None,
    ) -> None:
        """Configure one stateless composer with an immutable display budget.

        Existing callers can continue to instantiate ``ReportComposer()``.  A
        mode changes only allocation policy; it never changes the canonical
        report, deterministic ranking, or renderer contracts.
        """
        if not isinstance(mode, ReportMode):
            raise ValueError("mode must be a ReportMode instance.")
        if budget is not None and not isinstance(budget, PresentationBudget):
            raise TypeError("budget must be a PresentationBudget instance or None.")
        self._mode = mode
        self._budget = budget or PresentationBudget.for_mode(mode)

    def compose(
        self,
        report: EnhancedResearchReport,
        source_document: ParsedDocument | None = None,
        generated_on: date | None = None,
    ) -> PresentationModel:
        """Return one deterministic presentation model for an enhanced report."""
        self._validate_report(report)
        self._validate_source_document(source_document)
        self._validate_generated_on(generated_on)

        try:
            context = EnhancedReportRenderContext.from_report(report)
            confidence_by_source = self._confidence_by_source(report)
            primary_candidates = self._primary_finding_candidates(
                report,
                context,
                confidence_by_source,
            )
            appendix_candidates = self._appendix_finding_candidates(
                report,
                context,
                confidence_by_source,
                start_index=len(primary_candidates),
            )
            supported_section_candidates = self._supported_section_candidates(
                report,
                context,
                confidence_by_source,
                start_index=len(primary_candidates) + len(appendix_candidates),
            )
            curated_findings = self._curate_finding_candidates(
                primary_candidates
                + appendix_candidates
                + supported_section_candidates
            )
            executive_summary = self._executive_summary_paragraphs(
                report.executive_summary,
                tuple(candidate.card for candidate in curated_findings.cards),
                self._content_summary_limit(
                    self._budget.executive_summary_paragraph_limit
                ),
            )
            summary_covered, finding_pool = self._remove_summary_duplicates(
                curated_findings.cards,
                executive_summary,
            )
            primary_finding_pool = tuple(
                candidate
                for candidate in finding_pool
                if candidate.is_canonical and not candidate.is_appendix
            )
            appendix_finding_pool = tuple(
                candidate for candidate in finding_pool if candidate.is_appendix
            )
            supported_finding_pool = tuple(
                candidate
                for candidate in finding_pool
                if not candidate.is_canonical and not candidate.is_appendix
            )
            ranked_findings = tuple(
                sorted(primary_finding_pool, key=lambda candidate: candidate.sort_key)
            )
            selected_candidates, non_key_candidates = self._take(
                ranked_findings,
                self._budget.key_insights_limit,
            )

            technical_candidates, technical_remainder = self._take(
                tuple(
                    sorted(
                        non_key_candidates + supported_finding_pool,
                        key=lambda candidate: candidate.sort_key,
                    )
                ),
                self._budget.technical_analysis_limit,
            )
            canonical_remainder = tuple(
                candidate
                for candidate in technical_remainder
                if candidate.is_canonical
            )
            appendix_candidates_visible, hidden_canonical_candidates = self._take(
                tuple(
                    sorted(
                        appendix_finding_pool + canonical_remainder,
                        key=lambda candidate: candidate.sort_key,
                    )
                ),
                self._budget.appendix_findings_limit,
            )
            hidden_section_candidates = tuple(
                candidate
                for candidate in technical_remainder
                if not candidate.is_canonical
            )
            hidden_finding_cards = tuple(
                candidate.card
                for candidate in (
                    hidden_canonical_candidates
                    + hidden_section_candidates
                )
            )

            concept_candidates = self._concept_candidates(
                report,
                context,
                confidence_by_source,
                tuple(candidate.card for candidate in primary_candidates)
                + tuple(candidate.card for candidate in appendix_candidates),
            )
            curated_concepts = self._curate_concept_candidates(concept_candidates)
            ranked_concepts = tuple(
                sorted(curated_concepts.cards, key=lambda candidate: candidate.sort_key)
            )
            meaningful_concepts = tuple(
                candidate
                for candidate in ranked_concepts
                if self._is_meaningful_concept(candidate.card)
            )
            abbreviated_concepts = tuple(
                candidate
                for candidate in ranked_concepts
                if not self._is_meaningful_concept(candidate.card)
            )
            selected_concept_candidates, remaining_concepts = self._take(
                meaningful_concepts,
                self._budget.primary_concepts_limit,
            )
            appendix_concept_candidates, hidden_concept_candidates = self._take(
                remaining_concepts + abbreviated_concepts,
                self._budget.appendix_concepts_limit,
            )
            selected_concepts = tuple(
                candidate.card for candidate in selected_concept_candidates
            )
            appendix_concepts = tuple(
                candidate.card for candidate in appendix_concept_candidates
            )

            entity_result = self._entity_groups(
                report,
                context,
                confidence_by_source,
                self._budget.entities_per_category_limit,
            )
            entity_groups = entity_result.visible_groups
            hidden_entity_groups = entity_result.hidden_groups
            timeline_candidates = self._timeline_cards(
                report,
                context,
                confidence_by_source,
            )
            curated_timeline = self._curate_timeline_cards(timeline_candidates)
            timeline, hidden_timeline = self._take(
                curated_timeline.cards,
                self._budget.timeline_limit,
            )

            metric_result = self._metric_cards(report, source_document)
            visible_metrics, hidden_metrics = self._take(
                metric_result.cards,
                self._budget.metrics_limit,
            )

            all_visible_cards = (
                tuple(candidate.card for candidate in summary_covered)
                + tuple(candidate.card for candidate in selected_candidates)
                + tuple(candidate.card for candidate in technical_candidates)
                + tuple(candidate.card for candidate in appendix_candidates_visible)
            )
            visible_source_ids = self._visible_source_ids(
                all_visible_cards,
                selected_concepts + appendix_concepts,
                entity_groups,
                tuple(timeline),
            )
            reference_result = self._reference_cards(
                report,
                context,
                confidence_by_source,
            )
            reference_candidates = reference_result.cards
            supported_references = tuple(
                reference
                for reference in reference_candidates
                if set(reference.evidence.supporting_chunk_ids).intersection(
                    visible_source_ids
                )
            )
            hidden_references = tuple(
                reference
                for reference in reference_candidates
                if reference not in supported_references
            )
            main_references, appendix_references = self._take(
                supported_references,
                self._budget.primary_references_limit,
            )

            compression_statistics = self._compression_statistics(
                extracted_findings=(
                    len(primary_candidates)
                    + len(appendix_candidates)
                    + len(supported_section_candidates)
                ),
                displayed_findings=(
                    len(summary_covered)
                    + len(selected_candidates)
                    + len(technical_candidates)
                ),
                appendix_findings=len(appendix_candidates_visible),
                hidden_findings=len(hidden_canonical_candidates)
                + len(hidden_section_candidates),
                deduplicated_findings=curated_findings.deduplicated,
                artifact_findings=curated_findings.artifact_rejected,
                extracted_concepts=len(concept_candidates),
                displayed_concepts=len(selected_concepts),
                appendix_concepts=len(appendix_concepts),
                hidden_concepts=len(hidden_concept_candidates),
                deduplicated_concepts=curated_concepts.deduplicated,
                artifact_concepts=curated_concepts.artifact_rejected,
                entity_extracted=entity_result.extracted,
                entity_displayed=sum(len(group.entities) for group in entity_groups),
                entity_hidden=sum(
                    len(group.entities) for group in hidden_entity_groups
                ),
                entity_deduplicated=entity_result.deduplicated,
                entity_artifacts=entity_result.artifact_rejected,
                metric_result=metric_result,
                metric_displayed=len(visible_metrics),
                metric_hidden=len(hidden_metrics),
                timeline_extracted=len(timeline_candidates),
                timeline_displayed=len(timeline),
                timeline_hidden=len(hidden_timeline),
                timeline_deduplicated=curated_timeline.deduplicated,
                timeline_artifacts=curated_timeline.artifact_rejected,
                reference_extracted=reference_result.extracted,
                reference_displayed=len(main_references),
                reference_appendix=len(appendix_references),
                reference_hidden=len(hidden_references),
                reference_deduplicated=reference_result.deduplicated,
            )

            domain = self._domain(
                entity_groups,
                selected_candidates,
                technical_candidates,
            )
            cover = self._cover(
                report,
                source_document,
                generated_on,
                confidence_by_source,
                self._cited_source_ids(report),
                domain,
            )
            sections = self._sections(
                report,
                context,
                confidence_by_source,
                cover,
                executive_summary,
                selected_candidates,
                technical_candidates,
                tuple(candidate.card for candidate in appendix_candidates_visible),
                selected_concepts,
                appendix_concepts,
                entity_groups,
                tuple(timeline),
                main_references,
                appendix_references,
                tuple(visible_metrics),
                compression_statistics,
            )
            table_of_contents = TableOfContents(
                entries=tuple(
                    TableOfContentsEntry(
                        heading=section.heading,
                        anchor_id=section.anchor_id,
                    )
                    for section in sections
                )
            )
            return PresentationModel(
                cover=cover,
                table_of_contents=table_of_contents,
                sections=sections,
                mode=self._mode,
                budget=self._budget,
                hidden_content=HiddenPresentationData(
                    findings=hidden_finding_cards,
                    concepts=tuple(
                        candidate.card for candidate in hidden_concept_candidates
                    ),
                    entity_groups=hidden_entity_groups,
                    metrics=tuple(hidden_metrics),
                    unlabeled_metrics=metric_result.unlabeled_values,
                    timeline=tuple(hidden_timeline),
                    references=hidden_references,
                ),
                compression_statistics=compression_statistics,
            )
        except InvalidResearchReportError:
            raise
        except ReportCompositionError:
            raise
        except (AttributeError, KeyError, TypeError, ValidationError, ValueError) as exc:
            raise ReportCompositionError(
                "Unable to compose the enhanced report for presentation."
            ) from exc

    @staticmethod
    def _validate_report(report: object) -> None:
        """Defensively revalidate a report that may have bypassed Pydantic."""
        if not isinstance(report, EnhancedResearchReport):
            raise InvalidResearchReportError(
                "Input must be an EnhancedResearchReport instance."
            )
        if getattr(report, "__pydantic_extra__", None):
            raise InvalidResearchReportError(
                "EnhancedResearchReport must not contain extra fields."
            )
        try:
            payload = report.model_dump(mode="python", warnings="error")
            EnhancedResearchReport.model_validate(payload)
        except (AttributeError, TypeError, ValidationError, ValueError) as exc:
            raise InvalidResearchReportError(
                "EnhancedResearchReport failed structural validation."
            ) from exc

    @staticmethod
    def _validate_source_document(source_document: object) -> None:
        """Validate optional parsed metadata without changing document content."""
        if source_document is None:
            return
        if not isinstance(source_document, ParsedDocument):
            raise InvalidResearchReportError(
                "source_document must be a ParsedDocument instance or None."
            )
        if getattr(source_document, "__pydantic_extra__", None):
            raise InvalidResearchReportError(
                "ParsedDocument must not contain extra fields."
            )
        try:
            payload = source_document.model_dump(mode="python", warnings="error")
            ParsedDocument.model_validate(payload)
        except (AttributeError, TypeError, ValidationError, ValueError) as exc:
            raise InvalidResearchReportError(
                "ParsedDocument failed structural validation."
            ) from exc

        if source_document.character_count != len(source_document.extracted_text):
            raise InvalidResearchReportError(
                "ParsedDocument character_count does not match extracted_text."
            )
        if source_document.word_count != ReportComposer._word_count(
            source_document.extracted_text
        ):
            raise InvalidResearchReportError(
                "ParsedDocument word_count does not match extracted_text."
            )

    @staticmethod
    def _validate_generated_on(generated_on: object) -> None:
        """Accept only an explicit calendar date to preserve determinism."""
        if generated_on is None:
            return
        if type(generated_on) is not date or isinstance(generated_on, datetime):
            raise InvalidResearchReportError(
                "generated_on must be a datetime.date instance or None."
            )

    @staticmethod
    def _word_count(value: str) -> int:
        """Count whitespace-delimited words without allocating a split list."""
        count = 0
        in_word = False
        for character in value:
            if character.isspace():
                in_word = False
            elif not in_word:
                in_word = True
                count += 1
        return count

    @staticmethod
    def _confidence_by_source(report: EnhancedResearchReport) -> dict[UUID, float]:
        """Index source-ledger confidence values in deterministic evidence order."""
        return {
            evidence.chunk_id: evidence.confidence
            for evidence in report.synthesis_metadata.source_evidence
        }

    @classmethod
    def _primary_finding_candidates(
        cls,
        report: EnhancedResearchReport,
        context: EnhancedReportRenderContext,
        confidence_by_source: dict[UUID, float],
    ) -> tuple[_FindingCandidate, ...]:
        """Materialize authoritative primary findings without reordering truth."""
        intelligence_by_index = {}
        if report.report_intelligence is not None:
            intelligence_by_index = {
                finding.source_index: finding
                for finding in report.report_intelligence.findings
                if finding.source_kind == "finding"
            }

        candidates: list[_FindingCandidate] = []
        for index, (finding, rendered) in enumerate(
            zip(report.findings, context.findings, strict=True)
        ):
            enriched = intelligence_by_index.get(index)
            raw_confidence = (
                enriched.confidence
                if enriched is not None
                else cls._mean_confidence(
                    finding.supporting_chunk_ids,
                    confidence_by_source,
                )
            )
            references = enriched.references if enriched is not None else rendered.references
            evidence = cls._evidence(
                finding.supporting_chunk_ids,
                cls._labels_for(context, finding.supporting_chunk_ids),
                references,
                raw_confidence,
                rendered.confidence_label,
            )
            candidates.append(
                _FindingCandidate(
                    source_index=index,
                    card=InsightCard(
                        key=f"finding-{index + 1}",
                        title=rendered.title,
                        summary=rendered.summary,
                        importance=rendered.importance_label,
                        evidence=evidence,
                    ),
                    raw_confidence=raw_confidence,
                )
            )
        return tuple(candidates)

    @classmethod
    def _appendix_finding_candidates(
        cls,
        report: EnhancedResearchReport,
        context: EnhancedReportRenderContext,
        confidence_by_source: dict[UUID, float],
        start_index: int,
    ) -> tuple[_FindingCandidate, ...]:
        """Materialize secondary canonical findings for budgeted routing."""
        intelligence_by_index = {}
        if report.report_intelligence is not None:
            intelligence_by_index = {
                finding.source_index: finding
                for finding in report.report_intelligence.findings
                if finding.source_kind == "appendix"
            }

        candidates: list[_FindingCandidate] = []
        for index, (finding, rendered) in enumerate(
            zip(report.appendix_findings, context.appendix_findings, strict=True)
        ):
            enriched = intelligence_by_index.get(index)
            raw_confidence = (
                enriched.confidence
                if enriched is not None
                else cls._mean_confidence(
                    finding.supporting_chunk_ids,
                    confidence_by_source,
                )
            )
            references = enriched.references if enriched is not None else rendered.references
            candidates.append(
                _FindingCandidate(
                    source_index=start_index + index,
                    card=InsightCard(
                        key=f"appendix-finding-{index + 1}",
                        title=rendered.title,
                        summary=rendered.summary,
                        importance=rendered.importance_label,
                        evidence=cls._evidence(
                            finding.supporting_chunk_ids,
                            cls._labels_for(context, finding.supporting_chunk_ids),
                            references,
                            raw_confidence,
                            rendered.confidence_label,
                        ),
                    ),
                    raw_confidence=raw_confidence,
                    is_appendix=True,
                )
            )
        return tuple(candidates)

    @staticmethod
    def _take(
        values: tuple[_T, ...],
        limit: int | None,
    ) -> tuple[tuple[_T, ...], tuple[_T, ...]]:
        """Split an ordered collection without discarding any eligible value."""
        if limit is None:
            return values, ()
        return values[:limit], values[limit:]

    @classmethod
    def _curate_finding_candidates(
        cls,
        candidates: tuple[_FindingCandidate, ...],
    ) -> _CurationResult:
        """Merge meaningful display duplicates and reject parser artifacts once."""
        groups: list[list[_FindingCandidate]] = []
        exact_index: dict[str, int] = {}
        event_index: dict[tuple[str, ...], list[int]] = {}
        token_index: dict[str, list[int]] = {}
        deduplicated = 0
        artifact_rejected = 0

        for candidate in candidates:
            if cls._is_finding_artifact(candidate.card):
                artifact_rejected += 1
                continue
            normalized = cls._normalized_text(candidate.card.summary)
            tokens = cls._content_tokens(candidate.card.summary)
            matching_index = exact_index.get(normalized)
            if matching_index is None:
                possible: set[int] = set()
                for token in sorted(tokens):
                    possible.update(token_index.get(token, ()))
                    if len(possible) >= 128:
                        break
                for event_key in cls._event_keys(candidate.card):
                    possible.update(event_index.get(event_key, ()))
                matching_index = next(
                    (
                        index
                        for index in sorted(possible)[:128]
                        if cls._finding_cards_match(candidate.card, groups[index][0].card)
                    ),
                    None,
                )

            if matching_index is None:
                matching_index = len(groups)
                groups.append([candidate])
                for token in tokens:
                    indexed = token_index.setdefault(token, [])
                    if len(indexed) < 64:
                        indexed.append(matching_index)
                for event_key in cls._event_keys(candidate.card):
                    event_index.setdefault(event_key, []).append(matching_index)
            else:
                groups[matching_index].append(candidate)
                deduplicated += 1
            exact_index.setdefault(normalized, matching_index)

        return _CurationResult(
            cards=tuple(cls._merge_finding_group(group) for group in groups),
            deduplicated=deduplicated,
            artifact_rejected=artifact_rejected,
        )

    @staticmethod
    def _is_finding_artifact(card: InsightCard) -> bool:
        """Recognize non-narrative parser residue without hiding factual prose."""
        combined = f"{card.title} {card.summary}".strip()
        summary = ReportComposer._strip_terminal_punctuation(card.summary)
        if _RAW_ENUMERATION_PATTERN.fullmatch(summary):
            return True
        if _PAGE_ARTIFACT_PATTERN.fullmatch(summary):
            return True
        if ReportComposer._is_layout_observation(summary):
            return True
        if _NUMBERED_HEADING_PATTERN.fullmatch(card.title) and len(
            ReportComposer._content_tokens(summary)
        ) <= 2:
            return True
        tokens = ReportComposer._tokens(combined)
        if not tokens:
            return True
        return len(tokens) <= 2 and all(
            token.replace(".", "").replace(",", "").isdigit()
            for token in tokens
        )

    @staticmethod
    def _is_layout_observation(value: str) -> bool:
        """Identify low-value layout statements without discarding technical claims."""
        tokens = ReportComposer._content_tokens(value)
        if not tokens.intersection(_LAYOUT_OBSERVATION_TOKENS):
            return False
        if tokens.intersection(_SUBSTANTIVE_FINDING_TOKENS):
            return False
        meaningful = {
            token
            for token in tokens
            if token not in _LAYOUT_OBSERVATION_TOKENS
            and token not in _LAYOUT_CONTEXT_TOKENS
            and not token.replace(".", "").replace(",", "").isdigit()
        }
        return not meaningful

    @classmethod
    def _finding_cards_match(cls, left: InsightCard, right: InsightCard) -> bool:
        """Apply conservative lexical and structured-event duplicate matching."""
        left_normalized = cls._normalized_text(left.summary)
        right_normalized = cls._normalized_text(right.summary)
        if left_normalized == right_normalized:
            return True
        left_tokens = cls._content_tokens(left.summary)
        right_tokens = cls._content_tokens(right.summary)
        shared = len(left_tokens.intersection(right_tokens))
        union = len(left_tokens.union(right_tokens))
        if shared >= 3 and union and shared / union >= 0.85:
            return True
        left_events = cls._event_keys(left)
        right_events = cls._event_keys(right)
        return bool(left_events.intersection(right_events))

    @classmethod
    def _event_keys(cls, card: InsightCard) -> frozenset[tuple[str, ...]]:
        """Return narrow equivalence keys for source-stated events and page facts."""
        tokens = cls._content_tokens(card.title + " " + card.summary)
        numbers = tuple(_NUMBER_PATTERN.findall(card.title + " " + card.summary))
        keys: set[tuple[str, ...]] = set()
        if cls._is_page_count_statement(card):
            for value in numbers:
                keys.add(("page-count", value.replace(",", "")))

        # Event matching is intentionally stricter than a shared verb or noun.
        # A common subject such as ``PDF`` must not collapse separate events
        # (for example, different introductions in different years).  The
        # normalized event signature therefore requires a numeric/date anchor
        # and the complete stable set of non-generic content tokens.
        verbs = tokens.intersection(_EVENT_VERBS)
        content_tokens = tuple(
            sorted(
                token
                for token in tokens
                if token not in _EVENT_VERBS
                and token not in _STOP_TOKENS
                and token
                not in {"document", "records", "record", "report", "source"}
                and not token.replace(".", "").replace(",", "").isdigit()
            )
        )
        if numbers and content_tokens:
            normalized_numbers = tuple(value.replace(",", "") for value in numbers)
            for verb in verbs:
                keys.add(
                    (
                        "event",
                        cls._event_verb_stem(verb),
                        *normalized_numbers,
                        *content_tokens,
                    )
                )
        return frozenset(keys)

    @staticmethod
    def _is_page_count_statement(card: InsightCard) -> bool:
        """Recognize page totals without conflating ordinary page references."""
        return bool(
            _PAGE_COUNT_STATEMENT_PATTERN.search(
                card.title + " " + card.summary
            )
        )

    @staticmethod
    def _event_verb_stem(value: str) -> str:
        """Normalize only the fixed event vocabulary used for equivalence keys."""
        stems = {
            "adopted": "adopt",
            "announced": "announce",
            "approved": "approve",
            "established": "establish",
            "introduced": "introduce",
            "launched": "launch",
            "published": "publish",
            "released": "release",
            "standardized": "standardize",
        }
        return stems.get(value, value)

    @classmethod
    def _merge_finding_group(
        cls,
        members: list[_FindingCandidate],
    ) -> _FindingCandidate:
        """Materialize one best presentation card with unioned provenance."""
        best = min(
            members,
            key=lambda candidate: (
                -candidate.card.evidence.source_count,
                -len(candidate.card.evidence.references),
                -(
                    candidate.raw_confidence
                    if candidate.raw_confidence is not None
                    else -1.0
                ),
                -len(candidate.card.summary),
                candidate.source_index,
            ),
        )
        evidence = cls._merge_evidence(
            tuple(member.card.evidence for member in members),
            fallback_confidence=best.raw_confidence,
        )
        importance = max(
            (member.card.importance for member in members),
            key=lambda value: _IMPORTANCE_RANK.get(value or "", 0),
        )
        return _FindingCandidate(
            source_index=min(member.source_index for member in members),
            card=InsightCard(
                key=best.card.key,
                title=best.card.title,
                summary=best.card.summary,
                importance=importance,
                evidence=evidence,
            ),
            raw_confidence=evidence.confidence,
            is_canonical=any(member.is_canonical for member in members),
            is_appendix=all(member.is_appendix for member in members),
        )

    @staticmethod
    def _merge_evidence(
        values: tuple[PresentationEvidence, ...],
        *,
        fallback_confidence: float | None,
    ) -> PresentationEvidence:
        """Union ordered provenance without reordering or fabricating evidence."""
        source_ids: list[UUID] = []
        source_labels: list[str] = []
        references: list[str] = []
        seen_ids: set[UUID] = set()
        seen_labels: set[str] = set()
        seen_references: set[str] = set()
        confidences: list[float] = []
        confidence_label: str | None = None
        for value in values:
            if value.confidence is not None:
                confidences.append(value.confidence)
            if confidence_label is None and value.confidence_label is not None:
                confidence_label = value.confidence_label
            for source_id in value.supporting_chunk_ids:
                if source_id not in seen_ids:
                    seen_ids.add(source_id)
                    source_ids.append(source_id)
            for label in value.source_labels:
                if label not in seen_labels:
                    seen_labels.add(label)
                    source_labels.append(label)
            for reference in value.references:
                key = ReportComposer._normalized_reference_key(reference)
                if key and key not in seen_references:
                    seen_references.add(key)
                    references.append(reference)
        confidence = (
            sum(confidences) / len(confidences)
            if confidences
            else fallback_confidence
        )
        return PresentationEvidence(
            supporting_chunk_ids=tuple(source_ids),
            source_labels=tuple(source_labels),
            references=tuple(references),
            confidence=confidence,
            confidence_label=confidence_label,
            source_count=len(source_ids),
        )

    @classmethod
    def _remove_summary_duplicates(
        cls,
        candidates: tuple[_FindingCandidate, ...],
        paragraphs: tuple[str, ...],
    ) -> tuple[tuple[_FindingCandidate, ...], tuple[_FindingCandidate, ...]]:
        """Keep full finding prose out of a summary that already states it."""
        hidden: list[_FindingCandidate] = []
        retained: list[_FindingCandidate] = []
        for candidate in candidates:
            if any(
                cls._similar_text(candidate.card.summary, paragraph)
                for paragraph in paragraphs
            ):
                hidden.append(candidate)
            else:
                retained.append(candidate)
        return tuple(hidden), tuple(retained)

    @classmethod
    def _similar_text(cls, left: str, right: str) -> bool:
        """Compare narrative text conservatively for cross-section placement."""
        if cls._normalized_text(left) == cls._normalized_text(right):
            return True
        left_tokens = cls._content_tokens(left)
        right_tokens = cls._content_tokens(right)
        shared = len(left_tokens.intersection(right_tokens))
        union = len(left_tokens.union(right_tokens))
        return shared >= 3 and union > 0 and shared / union >= 0.85

    @classmethod
    def _supported_section_candidates(
        cls,
        report: EnhancedResearchReport,
        context: EnhancedReportRenderContext,
        confidence_by_source: dict[UUID, float],
        start_index: int,
    ) -> tuple[_FindingCandidate, ...]:
        """Treat optional AI sections as bounded technical material only."""
        return tuple(
            _FindingCandidate(
                source_index=start_index + index,
                card=InsightCard(
                    key=f"supported-section-{index + 1}",
                    title=section.heading,
                    summary=section.content,
                    importance=None,
                    evidence=cls._evidence(
                        section.supporting_chunk_ids,
                        cls._labels_for(context, section.supporting_chunk_ids),
                        cls._references_for_source_ids(
                            report,
                            section.supporting_chunk_ids,
                        ),
                        cls._mean_confidence(
                            section.supporting_chunk_ids,
                            confidence_by_source,
                        ),
                        None,
                    ),
                ),
                raw_confidence=cls._mean_confidence(
                    section.supporting_chunk_ids,
                    confidence_by_source,
                ),
                is_canonical=False,
            )
            for index, section in enumerate(report.sections)
        )

    @classmethod
    def _curate_concept_candidates(
        cls,
        candidates: tuple[_ConceptCandidate, ...],
    ) -> _CurationResult:
        """Merge concept duplicates into one card while retaining its evidence."""
        groups: dict[str, list[_ConceptCandidate]] = {}
        order: list[str] = []
        artifact_rejected = 0
        for candidate in candidates:
            if cls._is_concept_artifact(candidate.card):
                artifact_rejected += 1
                continue
            key = cls._normalized_text(candidate.card.concept)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(candidate)

        merged: list[_ConceptCandidate] = []
        deduplicated = 0
        for key in order:
            members = groups[key]
            best = min(members, key=lambda candidate: candidate.sort_key)
            if len(members) > 1:
                deduplicated += len(members) - 1
            related: list[str] = []
            seen_related: set[str] = set()
            for member in members:
                for concept in member.card.related_concepts:
                    normalized = cls._normalized_text(concept)
                    if normalized and normalized not in seen_related:
                        seen_related.add(normalized)
                        related.append(concept)
            evidence = cls._merge_evidence(
                tuple(member.card.evidence for member in members),
                fallback_confidence=best.raw_confidence,
            )
            merged.append(
                _ConceptCandidate(
                    source_index=min(member.source_index for member in members),
                    card=ConceptCard(
                        key=best.card.key,
                        concept=best.card.concept,
                        definition=best.card.definition,
                        related_concepts=tuple(related),
                        why_it_matters=best.card.why_it_matters,
                        evidence=evidence,
                    ),
                    raw_confidence=evidence.confidence,
                )
            )
        return _CurationResult(
            cards=tuple(merged),
            deduplicated=deduplicated,
            artifact_rejected=artifact_rejected,
        )

    @staticmethod
    def _is_concept_artifact(card: ConceptCard) -> bool:
        """Reject numeric/page residue while preserving legitimate definitions."""
        concept = ReportComposer._strip_terminal_punctuation(card.concept)
        definition = ReportComposer._strip_terminal_punctuation(card.definition)
        if _PAGE_ARTIFACT_PATTERN.fullmatch(concept):
            return True
        if _RAW_ENUMERATION_PATTERN.fullmatch(concept):
            return len(ReportComposer._content_tokens(definition)) <= 2
        return bool(
            _RAW_ENUMERATION_PATTERN.fullmatch(definition)
            or _PAGE_ARTIFACT_PATTERN.fullmatch(definition)
        )

    @staticmethod
    def _is_meaningful_concept(card: ConceptCard) -> bool:
        """Keep terse labels out of the primary concepts section.

        A primary concept must add an actual explanation beyond its title.  The
        source card remains eligible for the appendix, where compact labels can
        be retained without presenting them as complete definitions.
        """
        concept = ReportComposer._normalized_text(card.concept)
        definition = ReportComposer._normalized_text(card.definition)
        if not concept or not definition or concept == definition:
            return False
        return len(ReportComposer._content_tokens(card.definition)) >= 3

    @classmethod
    def _curate_timeline_cards(
        cls,
        cards: tuple[TimelineCard, ...],
    ) -> _CurationResult:
        """Keep only milestone timelines, dedupe them, and order chronologically."""
        groups: dict[str, list[TimelineCard]] = {}
        order: list[str] = []
        year_token_index: dict[tuple[str, str], list[str]] = {}
        artifact_rejected = 0
        for card in cards:
            if not cls._is_meaningful_timeline(card):
                artifact_rejected += 1
                continue
            key = cls._normalized_text(card.date + " " + card.description)
            matching_key = key if key in groups else None
            if matching_key is None:
                year = cls._timeline_year(card.date)
                if year is not None:
                    possible_keys: set[str] = set()
                    for token in cls._content_tokens(card.description):
                        possible_keys.update(year_token_index.get((year, token), ()))
                    matching_key = next(
                        (
                            candidate_key
                            for candidate_key in order
                            if candidate_key in possible_keys
                            and cls._similar_text(
                                card.description,
                                groups[candidate_key][0].description,
                            )
                        ),
                        None,
                    )
            if matching_key is None:
                groups[key] = []
                order.append(key)
                matching_key = key
                year = cls._timeline_year(card.date)
                if year is not None:
                    for token in cls._content_tokens(card.description):
                        indexed = year_token_index.setdefault((year, token), [])
                        if len(indexed) < 64:
                            indexed.append(key)
            groups[matching_key].append(card)

        merged: list[TimelineCard] = []
        deduplicated = 0
        for key in order:
            members = groups[key]
            best = min(
                members,
                key=lambda card: (
                    -card.evidence.source_count,
                    -(
                        card.evidence.confidence
                        if card.evidence.confidence is not None
                        else -1.0
                    ),
                    -len(card.evidence.references),
                ),
            )
            deduplicated += len(members) - 1
            merged.append(
                TimelineCard(
                    date=best.date,
                    description=best.description,
                    evidence=cls._merge_evidence(
                        tuple(card.evidence for card in members),
                        fallback_confidence=best.evidence.confidence,
                    ),
                )
            )
        ordered = tuple(
            card
            for _, card in sorted(
                enumerate(merged),
                key=lambda item: cls._timeline_sort_key(item[1].date, item[0]),
            )
        )
        return _CurationResult(
            cards=ordered,
            deduplicated=deduplicated,
            artifact_rejected=artifact_rejected,
        )

    @staticmethod
    def _timeline_year(value: str) -> str | None:
        """Return a sortable year only for common ISO and Month-Year values."""
        matched = re.match(r"^\s*(\d{4})", value)
        if matched:
            return matched.group(1)
        month_match = re.search(r"\b(\d{4})\s*$", value)
        return month_match.group(1) if month_match else None

    @classmethod
    def _is_meaningful_timeline(cls, card: TimelineCard) -> bool:
        """Reject parser residue while retaining structured source timeline events.

        A ``TimelineEvent`` is already canonical report data.  The composer
        therefore removes only unmistakable page/list residue instead of
        discarding a cited date merely because the extraction layer
        used neutral wording such as ``Document records the date 2026``.
        """
        description = cls._strip_terminal_punctuation(card.description)
        if (
            _RAW_ENUMERATION_PATTERN.fullmatch(description)
            or _PAGE_ARTIFACT_PATTERN.fullmatch(description)
            or cls._is_layout_observation(description)
        ):
            return False
        return len(cls._content_tokens(description)) >= 2

    @staticmethod
    def _timeline_sort_key(value: str, source_index: int) -> tuple[int, int, int, int]:
        """Sort common extracted dates without parsing locale-dependent prose."""
        matched = re.match(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$", value.strip())
        if matched:
            return (
                int(matched.group(1)),
                int(matched.group(2) or 0),
                int(matched.group(3) or 0),
                source_index,
            )
        months = {
            name: index
            for index, name in enumerate(
                (
                    "january", "february", "march", "april", "may", "june",
                    "july", "august", "september", "october", "november", "december",
                ),
                start=1,
            )
        }
        month_match = re.match(r"^([A-Za-z]+)\s+(\d{4})$", value.strip())
        if month_match and month_match.group(1).casefold() in months:
            return (
                int(month_match.group(2)),
                months[month_match.group(1).casefold()],
                0,
                source_index,
            )
        return (9999, 12, 31, source_index)

    @classmethod
    def _metric_cards(
        cls,
        report: EnhancedResearchReport,
        source_document: ParsedDocument | None,
    ) -> _MetricCurationResult:
        """Create only labelled metric cards; bare values remain count-only."""
        cards: list[MetricCard] = []
        unlabeled_values: list[str] = []
        seen: set[tuple[str, str]] = set()
        seen_unlabeled: set[str] = set()
        deduplicated = 0
        artifact_rejected = 0

        def add(label: str, value: str, key: str) -> None:
            nonlocal deduplicated
            normalized = (cls._normalized_text(label), cls._normalized_text(value))
            if not all(normalized):
                return
            if normalized in seen:
                deduplicated += 1
                return
            seen.add(normalized)
            cards.append(
                MetricCard(
                    key=key,
                    label=_SPACE_PATTERN.sub(" ", label).strip(),
                    value=_SPACE_PATTERN.sub(" ", value).strip(),
                    evidence=PresentationEvidence(),
                )
            )

        if source_document is not None and source_document.page_count is not None:
            add("Total Pages", str(source_document.page_count), "metric-total-pages")

        for index, value in enumerate(report.base_report.important_metrics, start=1):
            match = _LABELED_METRIC_PATTERN.fullmatch(value)
            if match is None:
                normalized_value = cls._normalized_text(value)
                if not normalized_value:
                    artifact_rejected += 1
                elif normalized_value in seen_unlabeled:
                    deduplicated += 1
                else:
                    seen_unlabeled.add(normalized_value)
                    unlabeled_values.append(_SPACE_PATTERN.sub(" ", value).strip())
                continue
            label, metric_value = match.groups()
            add(label, metric_value, f"metric-{index}")

        return _MetricCurationResult(
            cards=tuple(cards),
            unlabeled_values=tuple(unlabeled_values),
            deduplicated=deduplicated,
            artifact_rejected=artifact_rejected,
        )

    @staticmethod
    def _visible_source_ids(
        finding_cards: tuple[InsightCard, ...],
        concepts: tuple[ConceptCard, ...],
        entities: tuple[EntityPresentationGroup, ...],
        timeline: tuple[TimelineCard, ...],
    ) -> frozenset[UUID]:
        """Collect only source IDs supporting currently visible report material."""
        source_ids: set[UUID] = set()
        for card in finding_cards:
            source_ids.update(card.evidence.supporting_chunk_ids)
        for card in concepts:
            source_ids.update(card.evidence.supporting_chunk_ids)
        for group in entities:
            for entity in group.entities:
                source_ids.update(entity.evidence.supporting_chunk_ids)
        for card in timeline:
            source_ids.update(card.evidence.supporting_chunk_ids)
        return frozenset(source_ids)

    @staticmethod
    def _compression_statistics(
        *,
        extracted_findings: int,
        displayed_findings: int,
        appendix_findings: int,
        hidden_findings: int,
        deduplicated_findings: int,
        artifact_findings: int,
        extracted_concepts: int,
        displayed_concepts: int,
        appendix_concepts: int,
        hidden_concepts: int,
        deduplicated_concepts: int,
        artifact_concepts: int,
        entity_extracted: int,
        entity_displayed: int,
        entity_hidden: int,
        entity_deduplicated: int,
        entity_artifacts: int,
        metric_result: _MetricCurationResult,
        metric_displayed: int,
        metric_hidden: int,
        timeline_extracted: int,
        timeline_displayed: int,
        timeline_hidden: int,
        timeline_deduplicated: int,
        timeline_artifacts: int,
        reference_extracted: int,
        reference_displayed: int,
        reference_appendix: int,
        reference_hidden: int,
        reference_deduplicated: int,
    ) -> tuple[CompressionStatistic, ...]:
        """Return fixed accounting rows whose outcomes partition source items."""
        metric_extracted = (
            len(metric_result.cards)
            + len(metric_result.unlabeled_values)
            + metric_result.deduplicated
            + metric_result.artifact_rejected
        )
        return (
            CompressionStatistic(
                category="Findings",
                extracted=extracted_findings,
                displayed=displayed_findings,
                moved_to_appendix=appendix_findings,
                hidden=hidden_findings,
                deduplicated=deduplicated_findings,
                artifact_rejected=artifact_findings,
            ),
            CompressionStatistic(
                category="Concepts",
                extracted=extracted_concepts,
                displayed=displayed_concepts,
                moved_to_appendix=appendix_concepts,
                hidden=hidden_concepts,
                deduplicated=deduplicated_concepts,
                artifact_rejected=artifact_concepts,
            ),
            CompressionStatistic(
                category="Entities",
                extracted=entity_extracted,
                displayed=entity_displayed,
                moved_to_appendix=0,
                hidden=entity_hidden,
                deduplicated=entity_deduplicated,
                artifact_rejected=entity_artifacts,
            ),
            CompressionStatistic(
                category="Metrics",
                extracted=metric_extracted,
                displayed=metric_displayed,
                moved_to_appendix=0,
                hidden=metric_hidden + len(metric_result.unlabeled_values),
                deduplicated=metric_result.deduplicated,
                artifact_rejected=metric_result.artifact_rejected,
            ),
            CompressionStatistic(
                category="Timeline",
                extracted=timeline_extracted,
                displayed=timeline_displayed,
                moved_to_appendix=0,
                hidden=timeline_hidden,
                deduplicated=timeline_deduplicated,
                artifact_rejected=timeline_artifacts,
            ),
            CompressionStatistic(
                category="References",
                extracted=reference_extracted,
                displayed=reference_displayed,
                moved_to_appendix=reference_appendix,
                hidden=reference_hidden,
                deduplicated=reference_deduplicated,
                artifact_rejected=0,
            ),
        )

    @classmethod
    def _concept_candidates(
        cls,
        report: EnhancedResearchReport,
        context: EnhancedReportRenderContext,
        confidence_by_source: dict[UUID, float],
        finding_cards: tuple[InsightCard, ...],
    ) -> tuple[_ConceptCandidate, ...]:
        """Build source-aware concept cards from intelligence or legacy fields."""
        intelligence = report.report_intelligence
        candidates: list[_ConceptCandidate] = []
        if intelligence is not None and intelligence.definitions:
            for index, (definition, rendered) in enumerate(
                zip(intelligence.definitions, context.definitions, strict=True)
            ):
                card = ConceptCard(
                    key=f"concept-{index + 1}",
                    concept=rendered.concept,
                    definition=rendered.definition,
                    related_concepts=rendered.related_concepts,
                    why_it_matters=cls._why_it_matters(
                        rendered.concept,
                        finding_cards,
                    ),
                    evidence=cls._evidence(
                        definition.supporting_chunk_ids,
                        cls._labels_for(context, definition.supporting_chunk_ids),
                        definition.references,
                        definition.confidence,
                        rendered.confidence_label,
                    ),
                )
                candidates.append(
                    _ConceptCandidate(
                        source_index=index,
                        card=card,
                        raw_confidence=definition.confidence,
                    )
                )
            return tuple(candidates)

        for index, rendered in enumerate(context.definitions):
            candidates.append(
                _ConceptCandidate(
                    source_index=index,
                    card=ConceptCard(
                        key=f"concept-{index + 1}",
                        concept=rendered.concept,
                        definition=rendered.definition,
                        related_concepts=rendered.related_concepts,
                        why_it_matters=cls._why_it_matters(
                            rendered.concept,
                            finding_cards,
                        ),
                        evidence=cls._evidence(
                            (),
                            (),
                            rendered.references,
                            None,
                            rendered.confidence_label,
                        ),
                    ),
                    raw_confidence=None,
                )
            )
        return tuple(candidates)

    @classmethod
    def _entity_groups(
        cls,
        report: EnhancedResearchReport,
        context: EnhancedReportRenderContext,
        confidence_by_source: dict[UUID, float],
        limit: int | None,
    ) -> _EntityCurationResult:
        """Curate entities before allocating them to visible or hidden views."""
        intelligence = report.report_intelligence
        visible_groups: list[EntityPresentationGroup] = []
        hidden_groups: list[EntityPresentationGroup] = []
        extracted = 0
        deduplicated = 0
        artifact_rejected = 0

        source_groups: list[tuple[str, tuple[EntityCard, ...]]] = []
        if intelligence is None or not intelligence.entity_groups:
            for rendered_group in context.entity_groups:
                if not rendered_group.entities:
                    continue
                source_groups.append(
                    (
                        rendered_group.category or "Entities",
                        tuple(
                            EntityCard(
                                name=entity.name,
                                aliases=entity.aliases,
                                evidence=cls._evidence(
                                    (),
                                    (),
                                    entity.references,
                                    None,
                                    entity.confidence_label,
                                ),
                            )
                            for entity in rendered_group.entities
                        ),
                    )
                )
        else:
            rendered_by_category = {
                group.category: group
                for group in context.entity_groups
                if group.category
            }
            for source_group in intelligence.entity_groups:
                rendered_group = rendered_by_category.get(source_group.category)
                rendered_by_name = {
                    entity.name.casefold(): entity
                    for entity in (
                        rendered_group.entities if rendered_group is not None else ()
                    )
                }
                source_groups.append(
                    (
                        source_group.category,
                        tuple(
                            cls._entity_card(
                                entity,
                                rendered_by_name.get(entity.name.casefold()),
                                context,
                                confidence_by_source,
                            )
                            for entity in source_group.entities
                        ),
                    )
                )

        for category, cards in source_groups:
            extracted += len(cards)
            curated, group_deduplicated, group_artifacts = cls._curate_entity_cards(
                cards
            )
            deduplicated += group_deduplicated
            artifact_rejected += group_artifacts
            visible, hidden = cls._take(curated, limit)
            if visible:
                visible_groups.append(
                    EntityPresentationGroup(
                        category=category,
                        entities=visible,
                    )
                )
            if hidden:
                hidden_groups.append(
                    EntityPresentationGroup(
                        category=category,
                        entities=hidden,
                    )
                )
        return _EntityCurationResult(
            visible_groups=tuple(visible_groups),
            hidden_groups=tuple(hidden_groups),
            extracted=extracted,
            deduplicated=deduplicated,
            artifact_rejected=artifact_rejected,
        )

    @classmethod
    def _entity_card(
        cls,
        entity: object,
        rendered: RenderEntity | None,
        context: EnhancedReportRenderContext,
        confidence_by_source: dict[UUID, float],
    ) -> EntityCard:
        """Convert one full-ranked intelligence entity into a stable card."""
        source_ids = getattr(entity, "supporting_chunk_ids")
        references = getattr(entity, "references")
        confidence = getattr(entity, "confidence")
        source_labels = cls._labels_for(context, source_ids)
        confidence_label = rendered.confidence_label if rendered is not None else None
        return EntityCard(
            name=getattr(entity, "name"),
            aliases=getattr(entity, "aliases"),
            evidence=cls._evidence(
                source_ids,
                source_labels,
                references,
                confidence
                if confidence is not None
                else cls._mean_confidence(source_ids, confidence_by_source),
                confidence_label,
            ),
        )

    @classmethod
    def _curate_entity_cards(
        cls,
        cards: tuple[EntityCard, ...],
    ) -> tuple[tuple[EntityCard, ...], int, int]:
        """Remove obvious parser residue and exact normalized duplicates."""
        groups: dict[str, list[EntityCard]] = {}
        order: list[str] = []
        artifact_rejected = 0
        deduplicated = 0
        for card in cards:
            if cls._is_entity_artifact(card):
                artifact_rejected += 1
                continue
            key = cls._normalized_text(card.name)
            if key not in groups:
                groups[key] = []
                order.append(key)
            else:
                deduplicated += 1
            groups[key].append(card)
        return (
            tuple(cls._merge_entity_cards(groups[key]) for key in order),
            deduplicated,
            artifact_rejected,
        )

    @staticmethod
    def _is_entity_artifact(card: EntityCard) -> bool:
        """Reject only non-entity page, section, and numeric residue."""
        value = ReportComposer._strip_terminal_punctuation(card.name)
        return bool(
            _RAW_ENUMERATION_PATTERN.fullmatch(value)
            or _PAGE_ARTIFACT_PATTERN.fullmatch(value)
        )

    @classmethod
    def _merge_entity_cards(cls, members: list[EntityCard]) -> EntityCard:
        """Union duplicate entity evidence without creating a new entity name."""
        best = min(
            enumerate(members),
            key=lambda item: (
                -item[1].evidence.source_count,
                -len(item[1].evidence.references),
                -(
                    item[1].evidence.confidence
                    if item[1].evidence.confidence is not None
                    else -1.0
                ),
                item[0],
            ),
        )[1]
        aliases: list[str] = []
        seen_aliases: set[str] = {cls._normalized_text(best.name)}
        for member in members:
            for alias in member.aliases:
                normalized = cls._normalized_text(alias)
                if normalized and normalized not in seen_aliases:
                    seen_aliases.add(normalized)
                    aliases.append(alias)
        return EntityCard(
            name=best.name,
            aliases=tuple(aliases),
            evidence=cls._merge_evidence(
                tuple(member.evidence for member in members),
                fallback_confidence=best.evidence.confidence,
            ),
        )

    @classmethod
    def _timeline_cards(
        cls,
        report: EnhancedResearchReport,
        context: EnhancedReportRenderContext,
        confidence_by_source: dict[UUID, float],
    ) -> tuple[TimelineCard, ...]:
        """Prefer intelligent milestones and retain source-backed fallback dates."""
        intelligence = report.report_intelligence
        cards: list[TimelineCard] = []
        if intelligence is not None and intelligence.timeline:
            for event, rendered in zip(
                intelligence.timeline,
                context.timeline,
                strict=True,
            ):
                cards.append(
                    TimelineCard(
                        date=rendered.date,
                        description=rendered.description,
                        evidence=cls._evidence(
                            event.supporting_chunk_ids,
                            cls._labels_for(
                                context,
                                event.supporting_chunk_ids,
                            ),
                            event.references,
                            event.confidence,
                            rendered.confidence_label,
                        ),
                    )
                )
            return tuple(cards)

        for event, rendered in zip(
            report.base_report.timeline,
            context.timeline,
            strict=True,
        ):
            description = rendered.description
            if cls._normalized_text(description) == cls._normalized_text(
                f"Extracted date: {rendered.date}."
            ):
                description = f"Document records the date {rendered.date}."
            cards.append(
                TimelineCard(
                    date=rendered.date,
                    description=description,
                    evidence=cls._evidence(
                        event.supporting_chunk_ids,
                        cls._labels_for(context, event.supporting_chunk_ids),
                        rendered.references,
                        cls._mean_confidence(
                            event.supporting_chunk_ids,
                            confidence_by_source,
                        ),
                        rendered.confidence_label,
                    ),
                )
            )
        return tuple(cards)

    @classmethod
    def _reference_cards(
        cls,
        report: EnhancedResearchReport,
        context: EnhancedReportRenderContext,
        confidence_by_source: dict[UUID, float],
    ) -> _ReferenceCurationResult:
        """Collect every displayable reference once, retaining known evidence IDs."""
        label_to_id = {
            label: chunk_id for chunk_id, label in context.citation_index.labels.items()
        }
        accumulated: dict[
            str,
            tuple[str, list[UUID], list[str], set[UUID], set[str]],
        ] = {}
        extracted = 0
        deduplicated = 0

        def add(
            reference: str,
            source_ids: tuple[UUID, ...],
            source_labels: tuple[str, ...],
        ) -> None:
            nonlocal extracted, deduplicated
            normalized = cls._normalized_reference_key(reference)
            if not normalized:
                return
            extracted += 1
            current = accumulated.get(normalized)
            if current is None:
                ids: list[UUID] = []
                labels: list[str] = []
                seen_ids: set[UUID] = set()
                seen_labels: set[str] = set()
                accumulated[normalized] = (
                    reference,
                    ids,
                    labels,
                    seen_ids,
                    seen_labels,
                )
                current = accumulated[normalized]
            else:
                deduplicated += 1
            _, ids, labels, seen_ids, seen_labels = current
            for source_id in source_ids:
                if source_id not in seen_ids:
                    seen_ids.add(source_id)
                    ids.append(source_id)
            for label in source_labels:
                if label not in seen_labels:
                    seen_labels.add(label)
                    labels.append(label)

        for rendered in context.references:
            if rendered.reference is None:
                continue
            ids = cls._ids_for_reference_labels(rendered, label_to_id)
            labels = rendered.source_labels if ids else ()
            add(rendered.reference, ids, labels)

        for evidence in report.synthesis_metadata.source_evidence:
            label = context.citation_index.labels.get(evidence.chunk_id)
            for reference in evidence.references:
                add(
                    reference,
                    (evidence.chunk_id,),
                    (label,) if label is not None else (),
                )
        for reference in report.base_report.references:
            add(reference, (), ())

        cards: list[ReferenceCard] = []
        for reference, source_ids, labels, _, _ in accumulated.values():
            cards.append(
                ReferenceCard(
                    reference=reference,
                    evidence=cls._evidence(
                        tuple(source_ids),
                        tuple(labels),
                        (reference,),
                        cls._mean_confidence(
                            tuple(source_ids),
                            confidence_by_source,
                        ),
                        None,
                    ),
                )
            )
        return _ReferenceCurationResult(
            cards=tuple(cards),
            extracted=extracted,
            deduplicated=deduplicated,
        )

    @staticmethod
    def _ids_for_reference_labels(
        rendered: RenderReference,
        label_to_id: dict[str, UUID],
    ) -> tuple[UUID, ...]:
        """Recover raw IDs only when all human labels map to known chunks."""
        source_ids = tuple(
            label_to_id[label]
            for label in rendered.source_labels
            if label in label_to_id
        )
        if len(source_ids) != len(rendered.source_labels):
            return ()
        return source_ids

    def _sections(
        self,
        report: EnhancedResearchReport,
        context: EnhancedReportRenderContext,
        confidence_by_source: dict[UUID, float],
        cover: DocumentMetadata,
        executive_summary: tuple[str, ...],
        selected_candidates: tuple[_FindingCandidate, ...],
        technical_candidates: tuple[_FindingCandidate, ...],
        appendix_cards: tuple[InsightCard, ...],
        selected_concepts: tuple[ConceptCard, ...],
        appendix_concepts: tuple[ConceptCard, ...],
        entity_groups: tuple[EntityPresentationGroup, ...],
        timeline: tuple[TimelineCard, ...],
        main_references: tuple[ReferenceCard, ...],
        appendix_references: tuple[ReferenceCard, ...],
        metrics: tuple[MetricCard, ...],
        compression_statistics: tuple[CompressionStatistic, ...],
    ) -> tuple[PresentationSection, ...]:
        """Create the complete fixed report body and its typed payloads."""
        selected_cards = tuple(candidate.card for candidate in selected_candidates)
        technical_cards = tuple(candidate.card for candidate in technical_candidates)
        all_finding_cards = selected_cards + technical_cards + appendix_cards
        abstract = self._abstract(
            executive_summary,
            selected_cards + technical_cards,
            self._budget.abstract_word_limit,
        )
        report_guide = self._report_guide_intro()
        overview = self._overview_intro(cover)
        technical_groups = self._technical_groups(technical_cards)
        appendix_groups = self._appendix_groups(
            appendix_cards,
            appendix_concepts,
            appendix_references,
            self._appendix_statistics_tables(
                compression_statistics,
                self._budget.evidence_table_row_limit,
            ),
        )
        evidence_tables = self._evidence_tables(
            all_finding_cards,
            selected_concepts + appendix_concepts,
            main_references + appendix_references,
            metrics,
            compression_statistics,
            self._budget.evidence_table_row_limit,
        )
        executive_intro = (
            self._executive_summary_intro()
            if self._budget.executive_summary_paragraph_limit != 0
            else ()
        )
        major_findings_intro = self._major_findings_intro(selected_cards)
        technical_intro = self._technical_analysis_intro(technical_cards)
        timeline_intro = self._historical_evolution_intro(timeline)
        concepts_intro = self._key_concepts_intro(selected_concepts)
        evidence_intro = (
            self._evidence_summary_intro()
            if self._budget.evidence_table_row_limit != 0
            else ()
        )

        payloads: dict[str, dict[str, object]] = {
            "abstract": {"intro": abstract},
            "document-overview": {
                "intro": overview,
                "entity_groups": entity_groups,
            },
            "research-methodology": {"intro": report_guide},
            "executive-summary": {"intro": executive_intro + executive_summary},
            "key-insights": {
                "intro": major_findings_intro,
                "finding_groups": (
                    (
                        GroupedFinding(
                            heading=_PRIMARY_FINDING_HEADING,
                            findings=selected_cards,
                        ),
                    )
                    if selected_cards
                    else ()
                )
            },
            "technical-analysis": {
                "intro": technical_intro,
                "finding_groups": technical_groups,
            },
            "historical-timeline": {
                "intro": timeline_intro,
                "timeline": timeline,
            },
            "important-concepts": {
                "intro": concepts_intro,
                "concepts": selected_concepts,
            },
            "evidence-summary": {
                "intro": evidence_intro,
                "evidence_tables": evidence_tables,
                "references": main_references,
            },
            "appendix": {"appendix_groups": appendix_groups},
        }
        return tuple(
            PresentationSection(
                key=key,
                heading=heading,
                anchor_id=anchor_id,
                **payloads[key],
            )
            for key, heading, anchor_id in PRESENTATION_SECTION_SPECS
        )

    @classmethod
    def _cover(
        cls,
        report: EnhancedResearchReport,
        source_document: ParsedDocument | None,
        generated_on: date | None,
        confidence_by_source: dict[UUID, float],
        cited_source_ids: tuple[UUID, ...],
        domain: str,
    ) -> DocumentMetadata:
        """Build deterministic cover information without reading wall-clock time."""
        source_title = None
        filename = None
        file_type = None
        page_count = None
        if source_document is not None:
            possible_title = source_document.metadata.get("title")
            if isinstance(possible_title, str) and possible_title.strip():
                source_title = possible_title.strip()
            filename = source_document.filename
            file_type = source_document.file_type.upper()
            page_count = source_document.page_count

        source_ids = tuple(confidence_by_source)
        if not source_ids:
            source_ids = cited_source_ids
        mean_confidence = cls._mean_confidence(source_ids, confidence_by_source)
        return DocumentMetadata(
            title=source_title or filename or report.base_report.title,
            filename=filename,
            file_type=file_type,
            page_count=page_count,
            generated_on=generated_on,
            knowledge_object_count=len(source_ids),
            evidence_source_count=len(source_ids),
            mean_confidence=mean_confidence,
            status=cls._status(report),
            domain=domain,
            provider=report.synthesis_metadata.provider,
            model=report.synthesis_metadata.model,
        )

    @staticmethod
    def _status(report: EnhancedResearchReport) -> str:
        """Return the exact deterministic cover label for synthesis provenance."""
        metadata = report.synthesis_metadata
        if metadata.fallback:
            return "Deterministic fallback"
        if metadata.enhanced:
            return "AI-enhanced"
        return "Deterministic report"

    @classmethod
    def _domain(
        cls,
        entity_groups: tuple[EntityPresentationGroup, ...],
        selected_candidates: tuple[_FindingCandidate, ...],
        technical_candidates: tuple[_FindingCandidate, ...],
    ) -> str:
        """Select one conservative domain from already-present report evidence."""
        scores = {domain: 0 for domain in _DOMAIN_ORDER}
        for group in entity_groups:
            domain = _DOMAIN_CATEGORY_SCORES.get(group.category)
            if domain is not None:
                scores[domain] += len(group.entities)
        for candidate in selected_candidates + technical_candidates:
            domain = _DOMAIN_THEME_SCORES.get(cls._technical_theme(candidate.card))
            if domain is not None:
                scores[domain] += 1
        highest = max(scores.values(), default=0)
        if highest == 0:
            return "Undetermined"
        return next(domain for domain in _DOMAIN_ORDER if scores[domain] == highest)

    @classmethod
    def _abstract(
        cls,
        executive_summary: tuple[str, ...],
        selected_cards: tuple[InsightCard, ...],
        word_limit: int | None,
    ) -> tuple[str, ...]:
        """Build a narrative extractive abstract within the active budget."""
        source_text = list(executive_summary) + [card.summary for card in selected_cards]
        sentences: list[str] = []
        seen: set[str] = set()
        words_used = 0
        for text in source_text:
            for sentence in cls._sentences(text):
                if cls._looks_like_metric_or_list_fragment(sentence):
                    continue
                normalized = cls._normalized_text(sentence)
                if not normalized or normalized in seen:
                    continue
                sentence_words = sentence.split()
                if word_limit is not None:
                    remaining = word_limit - words_used
                    if remaining <= 0:
                        break
                    if len(sentence_words) > remaining:
                        sentence = " ".join(sentence_words[:remaining])
                        sentence_words = sentence.split()
                sentences.append(sentence)
                seen.add(normalized)
                words_used += len(sentence_words)
                if word_limit is not None and words_used >= word_limit:
                    break
            if word_limit is not None and words_used >= word_limit:
                break
        return (" ".join(sentences),) if sentences else ()

    @classmethod
    def _executive_summary_paragraphs(
        cls,
        executive_summary: str,
        finding_cards: tuple[InsightCard, ...],
        paragraph_limit: int | None,
    ) -> tuple[str, ...]:
        """Retain non-duplicate source paragraphs without repeating a finding verbatim."""
        if paragraph_limit == 0:
            return ()
        finding_text = {
            cls._normalized_text(card.summary) for card in finding_cards
        }
        paragraphs: list[str] = []
        seen: set[str] = set()
        for raw_paragraph in _PARAGRAPH_SPLIT_PATTERN.split(executive_summary):
            paragraph = _SPACE_PATTERN.sub(" ", raw_paragraph).strip()
            normalized = cls._normalized_text(paragraph)
            if (
                not normalized
                or normalized in seen
                or normalized in finding_text
            ):
                continue
            seen.add(normalized)
            paragraphs.append(paragraph)
            if paragraph_limit is not None and len(paragraphs) == paragraph_limit:
                break
        return tuple(paragraphs)

    @staticmethod
    def _content_summary_limit(limit: int | None) -> int | None:
        """Reserve one paragraph for the deterministic executive introduction."""
        if limit is None:
            return None
        return max(limit - 1, 0)

    @staticmethod
    def _looks_like_metric_or_list_fragment(value: str) -> bool:
        """Avoid promoting raw lists and numeric fragments into abstract prose."""
        stripped = value.strip()
        return bool(
            _RAW_ENUMERATION_PATTERN.fullmatch(stripped)
            or _PAGE_ARTIFACT_PATTERN.fullmatch(stripped)
            or _LABELED_METRIC_PATTERN.fullmatch(stripped)
        )

    @staticmethod
    def _report_guide_intro() -> tuple[str, ...]:
        """Explain the editorial reading order without exposing pipeline stages."""
        return (
            "The report moves from the document's central themes to its "
            "technical details, historical context, and supporting references.",
        )

    @staticmethod
    def _overview_intro(cover: DocumentMetadata) -> tuple[str, ...]:
        """Describe available source metadata without substituting placeholders."""
        type_text = cover.file_type or "Not available"
        page_text = str(cover.page_count) if cover.page_count is not None else "Not available"
        return (
            "This overview establishes the document's subject area and the "
            "available publication details.",
            f"The document is classified in {cover.domain}; source type: "
            f"{type_text}; page count: {page_text}.",
        )

    @staticmethod
    def _executive_summary_intro() -> tuple[str, ...]:
        """Frame the supplied summary as the document's central account."""
        return (
            "This summary presents the document's central themes in concise form.",
        )

    @staticmethod
    def _major_findings_intro(
        cards: tuple[InsightCard, ...],
    ) -> tuple[str, ...]:
        """Introduce ranked findings only when the section has material."""
        if not cards:
            return ()
        return (
            "The following findings are prioritized by supporting evidence, "
            "confidence, distinctiveness, and relevance to the document's subject.",
        )

    @staticmethod
    def _technical_analysis_intro(
        cards: tuple[InsightCard, ...],
    ) -> tuple[str, ...]:
        """Explain the purpose of the themed technical analysis section."""
        if not cards:
            return ()
        return (
            "This section organizes the remaining material into technical themes, "
            "highlighting implementation details, standards, and engineering considerations.",
        )

    @staticmethod
    def _historical_evolution_intro(
        timeline: tuple[TimelineCard, ...],
    ) -> tuple[str, ...]:
        """Frame chronological material only when meaningful milestones exist."""
        if not timeline:
            return ()
        return (
            "The milestones below place the document's historical evidence in chronological order.",
        )

    @staticmethod
    def _key_concepts_intro(
        concepts: tuple[ConceptCard, ...],
    ) -> tuple[str, ...]:
        """Introduce only definitions substantial enough for primary display."""
        if not concepts:
            return ()
        return (
            "These concepts provide the terminology needed to interpret the document's principal themes.",
        )

    @staticmethod
    def _evidence_summary_intro() -> tuple[str, ...]:
        """Describe the supporting tables without narrating extraction stages."""
        return (
            "The following tables summarize the report's evidence coverage, confidence, and selected metrics.",
        )

    @classmethod
    def _technical_groups(
        cls,
        cards: tuple[InsightCard, ...],
    ) -> tuple[GroupedFinding, ...]:
        """Route non-key primary findings into stable technical themes only."""
        grouped: dict[str, list[InsightCard]] = {
            heading: [] for heading in _TECHNICAL_THEME_ORDER
        }
        for card in cards:
            grouped[cls._technical_theme(card)].append(card)
        return tuple(
            GroupedFinding(heading=heading, findings=tuple(grouped[heading]))
            for heading in _TECHNICAL_THEME_ORDER
            if grouped[heading]
        )

    @classmethod
    def _enhanced_sections_group(
        cls,
        report: EnhancedResearchReport,
        context: EnhancedReportRenderContext,
        confidence_by_source: dict[UUID, float],
    ) -> tuple[GroupedFinding, ...]:
        """Retain optional AI thematic sections as source-backed technical cards."""
        if not report.sections:
            return ()
        cards = tuple(
            InsightCard(
                key=f"supported-section-{index + 1}",
                title=section.heading,
                summary=section.content,
                importance=None,
                evidence=PresentationEvidence(
                    supporting_chunk_ids=section.supporting_chunk_ids,
                    source_labels=cls._labels_for(
                        context,
                        section.supporting_chunk_ids,
                    ),
                    references=cls._references_for_source_ids(
                        report,
                        section.supporting_chunk_ids,
                    ),
                    confidence=cls._mean_confidence(
                        section.supporting_chunk_ids,
                        confidence_by_source,
                    ),
                    confidence_label=None,
                    source_count=len(section.supporting_chunk_ids),
                ),
            )
            for index, section in enumerate(report.sections)
        )
        return (GroupedFinding(heading="Supported Sections", findings=cards),)

    @classmethod
    def _appendix_groups(
        cls,
        appendix_cards: tuple[InsightCard, ...],
        appendix_concepts: tuple[ConceptCard, ...],
        appendix_references: tuple[ReferenceCard, ...],
        statistics_tables: tuple[EvidenceTable, ...],
    ) -> tuple[AppendixGroup, ...]:
        """Place bounded supporting material in a stable appendix order."""
        groups: list[AppendixGroup] = []
        if appendix_cards:
            groups.append(
                AppendixGroup(heading="Additional Findings", findings=appendix_cards)
            )
        if appendix_concepts:
            groups.append(
                AppendixGroup(
                    heading="Additional Concepts",
                    concepts=appendix_concepts,
                )
            )
        if appendix_references:
            groups.append(
                AppendixGroup(
                    heading="Supporting References",
                    references=appendix_references,
                )
            )
        if statistics_tables:
            groups.append(
                AppendixGroup(
                    heading="Supporting Statistics",
                    evidence_tables=statistics_tables,
                )
            )
        return tuple(groups)

    @classmethod
    def _legacy_evidence_tables(
        cls,
        finding_cards: tuple[InsightCard, ...],
        concept_cards: tuple[ConceptCard, ...],
        references: tuple[ReferenceCard, ...],
        metrics: tuple[str, ...],
    ) -> tuple[EvidenceTable, ...]:
        """Build compact deterministic summary tables without raw UUIDs."""
        importance_counts = Counter(
            card.importance or "Not available" for card in finding_cards
        )
        importance_rows = tuple(
            (label, str(importance_counts.get(label, 0)))
            for label in ("HIGH", "MEDIUM", "LOW", "Not available")
            if importance_counts.get(label, 0) or not finding_cards
        )
        if not importance_rows:
            importance_rows = (("Not available", "0"),)

        confidence_counts = Counter(
            cls._confidence_band(card.evidence.confidence) for card in finding_cards
        )
        confidence_rows = tuple(
            (label, str(confidence_counts.get(label, 0)))
            for label in ("90–100%", "75–89%", "60–74%", "Below 60%", "Not available")
            if confidence_counts.get(label, 0) or not finding_cards
        )
        if not confidence_rows:
            confidence_rows = (("Not available", "0"),)

        supported = sorted(
            finding_cards,
            key=lambda card: (
                -card.evidence.source_count,
                -(
                    card.evidence.confidence
                    if card.evidence.confidence is not None
                    else -1.0
                ),
                card.key,
            ),
        )[: PresentationBudget.professional().evidence_table_row_limit]
        supported_rows = tuple(
            (card.title, str(card.evidence.source_count)) for card in supported
        ) or (("Not available", "0"),)

        cited_concepts = sorted(
            concept_cards,
            key=lambda card: (
                -len(card.evidence.references),
                -card.evidence.source_count,
                card.concept.casefold(),
            ),
        )[: PresentationBudget.professional().evidence_table_row_limit]
        concept_rows = tuple(
            (card.concept, str(len(card.evidence.references)))
            for card in cited_concepts
        ) or (("Not available", "0"),)

        sources_with_references = len(
            {
                source_id
                for reference in references
                if reference.evidence.references
                for source_id in reference.evidence.supporting_chunk_ids
            }
        )
        reference_rows = (
            ("Displayed references", str(len(references))),
            ("Sources with references", str(sources_with_references)),
        )
        tables = [
            EvidenceTable(
                title="Finding Importance",
                columns=("Importance", "Findings"),
                rows=importance_rows,
            ),
            EvidenceTable(
                title="Confidence Distribution",
                columns=("Range", "Findings"),
                rows=confidence_rows,
            ),
            EvidenceTable(
                title="Most Supported Findings",
                columns=("Finding", "Sources"),
                rows=supported_rows,
            ),
            EvidenceTable(
                title="Most Cited Concepts",
                columns=("Concept", "References"),
                rows=concept_rows,
            ),
            EvidenceTable(
                title="Reference Statistics",
                columns=("Measure", "Count"),
                rows=reference_rows,
            ),
        ]
        if metrics:
            tables.append(
                EvidenceTable(
                    title="Reported Metrics",
                    columns=("Metric",),
                    rows=tuple((metric,) for metric in metrics),
                )
            )
        return tuple(tables)

    @classmethod
    def _evidence_tables(
        cls,
        finding_cards: tuple[InsightCard, ...],
        concept_cards: tuple[ConceptCard, ...],
        references: tuple[ReferenceCard, ...],
        metrics: tuple[MetricCard, ...],
        compression_statistics: tuple[CompressionStatistic, ...],
        row_limit: int | None,
    ) -> tuple[EvidenceTable, ...]:
        """Build budgeted report-level evidence and metric summaries."""
        if row_limit == 0:
            return (
                EvidenceTable(
                    title="Key Metrics",
                    columns=("Metric", "Value"),
                    rows=tuple((metric.label, metric.value) for metric in metrics),
                ),
            ) if metrics else ()
        compression_rows = cls._limit_rows(
            tuple(
                (
                    statistic.category,
                    str(statistic.extracted),
                    str(statistic.displayed),
                    str(statistic.moved_to_appendix),
                    str(statistic.hidden),
                )
                for statistic in compression_statistics
            ),
            row_limit,
        )
        importance_counts = Counter(
            card.importance or "Not available" for card in finding_cards
        )
        importance_rows = cls._limit_rows(
            tuple(
                (label, str(importance_counts.get(label, 0)))
                for label in ("HIGH", "MEDIUM", "LOW", "Not available")
                if importance_counts.get(label, 0) or not finding_cards
            ),
            row_limit,
        ) or (("Not available", "0"),)
        supported = sorted(
            finding_cards,
            key=lambda card: (
                -card.evidence.source_count,
                -(
                    card.evidence.confidence
                    if card.evidence.confidence is not None
                    else -1.0
                ),
                card.key,
            ),
        )
        highest = max(
            finding_cards,
            key=lambda card: (
                card.evidence.confidence
                if card.evidence.confidence is not None
                else -1.0
            ),
            default=None,
        )
        most_supported = supported[0] if supported else None
        source_ids = {
            source_id
            for card in finding_cards
            for source_id in card.evidence.supporting_chunk_ids
        }
        source_ids.update(
            source_id
            for card in concept_cards
            for source_id in card.evidence.supporting_chunk_ids
        )
        sources_with_references = len(
            {
                source_id
                for reference in references
                if reference.evidence.references
                for source_id in reference.evidence.supporting_chunk_ids
            }
        )
        quality_rows = cls._limit_rows(
            (
                ("Evidence sources", str(len(source_ids))),
                ("Average confidence", cls._confidence_text(cls._average_confidence(finding_cards))),
                (
                    "Highest-confidence finding",
                    highest.title if highest is not None else "Not available",
                ),
                (
                    "Most-supported finding",
                    most_supported.title if most_supported is not None else "Not available",
                ),
                ("Displayed references", str(len(references))),
                ("Sources with references", str(sources_with_references)),
            ),
            row_limit,
        )
        tables: list[EvidenceTable] = [
            EvidenceTable(
                title="Compression Statistics",
                columns=("Category", "Extracted", "Displayed", "Appendix", "Hidden"),
                rows=compression_rows,
            ),
            EvidenceTable(
                title="Finding Importance",
                columns=("Importance", "Findings"),
                rows=importance_rows,
            ),
            EvidenceTable(
                title="Evidence Quality",
                columns=("Measure", "Value"),
                rows=quality_rows,
            ),
        ]
        if metrics:
            tables.append(
                EvidenceTable(
                    title="Key Metrics",
                    columns=("Metric", "Value"),
                    rows=tuple((metric.label, metric.value) for metric in metrics),
                )
            )
        return tuple(tables)

    @staticmethod
    def _limit_rows(
        rows: tuple[tuple[str, ...], ...],
        limit: int | None,
    ) -> tuple[tuple[str, ...], ...]:
        """Apply a deterministic table budget without rewriting values."""
        return rows if limit is None else rows[:limit]

    @staticmethod
    def _average_confidence(cards: tuple[InsightCard, ...]) -> float | None:
        """Calculate a raw confidence mean for report-level evidence context."""
        values = tuple(
            card.evidence.confidence
            for card in cards
            if card.evidence.confidence is not None
        )
        return sum(values) / len(values) if values else None

    @staticmethod
    def _confidence_text(confidence: float | None) -> str:
        """Render optional raw confidence without inventing a quality score."""
        return f"{round(confidence * 100)}%" if confidence is not None else "Not available"

    @classmethod
    def _appendix_statistics_tables(
        cls,
        statistics: tuple[CompressionStatistic, ...],
        row_limit: int | None,
    ) -> tuple[EvidenceTable, ...]:
        """Describe compression choices without revealing hidden content."""
        if row_limit == 0:
            return ()
        rows = tuple(
            (
                statistic.category,
                str(statistic.deduplicated),
                str(statistic.artifact_rejected),
                str(statistic.hidden),
            )
            for statistic in statistics
            if (
                statistic.deduplicated
                or statistic.artifact_rejected
                or statistic.hidden
            )
        )
        if not rows:
            return ()
        return (
            EvidenceTable(
                title="Composition Details",
                columns=("Category", "Merged", "Artifacts", "Hidden"),
                rows=cls._limit_rows(rows, row_limit),
            ),
        )

    @staticmethod
    def _confidence_band(confidence: float | None) -> str:
        """Group raw confidence for a readable evidence-summary table."""
        if confidence is None:
            return "Not available"
        if confidence >= 0.9:
            return "90–100%"
        if confidence >= 0.75:
            return "75–89%"
        if confidence >= 0.6:
            return "60–74%"
        return "Below 60%"

    @classmethod
    def _why_it_matters(
        cls,
        concept: str,
        finding_cards: tuple[InsightCard, ...],
    ) -> str | None:
        """Link a concept to an existing finding only when tokens overlap."""
        concept_tokens = cls._tokens(concept)
        if not concept_tokens:
            return None
        for card in finding_cards:
            if concept_tokens.intersection(cls._tokens(card.title + " " + card.summary)):
                return f"Related finding: {card.title}."
        return "Clarifies terminology used in the analyzed document."

    @classmethod
    def _technical_theme(cls, card: InsightCard) -> str:
        """Classify a finding only for display routing, never persisted truth."""
        tokens = cls._tokens(card.title + " " + card.summary)
        for heading, terms in _TECHNICAL_THEME_TERMS:
            if tokens.intersection(terms):
                return heading
        return "General"

    @staticmethod
    def _evidence(
        source_ids: tuple[UUID, ...],
        source_labels: tuple[str, ...],
        references: tuple[str, ...],
        confidence: float | None,
        confidence_label: str | None,
    ) -> PresentationEvidence:
        """Create strict immutable evidence while preserving source order."""
        return PresentationEvidence(
            supporting_chunk_ids=source_ids,
            source_labels=source_labels,
            references=references,
            confidence=confidence,
            confidence_label=confidence_label,
            source_count=len(source_ids),
        )

    @staticmethod
    def _labels_for(
        context: EnhancedReportRenderContext,
        source_ids: tuple[UUID, ...],
    ) -> tuple[str, ...]:
        """Translate retained raw provenance to Source N labels safely."""
        try:
            return context.citation_index.labels_for(source_ids)
        except KeyError as exc:
            raise InvalidResearchReportError(
                "Composed content referenced an unknown source chunk."
            ) from exc

    @staticmethod
    def _mean_confidence(
        source_ids: tuple[UUID, ...],
        confidence_by_source: dict[UUID, float],
    ) -> float | None:
        """Calculate a deterministic raw confidence mean when ledger data exists."""
        values = tuple(
            confidence_by_source[source_id]
            for source_id in source_ids
            if source_id in confidence_by_source
        )
        if not values:
            return None
        return sum(values) / len(values)

    @staticmethod
    def _references_for_source_ids(
        report: EnhancedResearchReport,
        source_ids: tuple[UUID, ...],
    ) -> tuple[str, ...]:
        """Union source-ledger citations without touching canonical metadata."""
        wanted = set(source_ids)
        references: list[str] = []
        seen: set[str] = set()
        for evidence in report.synthesis_metadata.source_evidence:
            if evidence.chunk_id not in wanted:
                continue
            for reference in evidence.references:
                key = ReportComposer._normalized_reference_key(reference)
                if key and key not in seen:
                    seen.add(key)
                    references.append(reference)
        return tuple(references)

    @staticmethod
    def _cited_source_ids(report: EnhancedResearchReport) -> tuple[UUID, ...]:
        """Gather unique claim provenance in deterministic report order."""
        source_ids: list[UUID] = []
        seen: set[UUID] = set()

        def add(values: Iterable[UUID]) -> None:
            for source_id in values:
                if source_id not in seen:
                    seen.add(source_id)
                    source_ids.append(source_id)

        for finding in report.findings:
            add(finding.supporting_chunk_ids)
        for finding in report.appendix_findings:
            add(finding.supporting_chunk_ids)
        for event in report.base_report.timeline:
            add(event.supporting_chunk_ids)
        for section in report.sections:
            add(section.supporting_chunk_ids)
        if report.report_intelligence is not None:
            for finding in report.report_intelligence.findings:
                add(finding.supporting_chunk_ids)
            for definition in report.report_intelligence.definitions:
                add(definition.supporting_chunk_ids)
            for event in report.report_intelligence.timeline:
                add(event.supporting_chunk_ids)
            for reference in report.report_intelligence.references:
                add(reference.supporting_chunk_ids)
            for group in report.report_intelligence.entity_groups:
                for entity in group.entities:
                    add(entity.supporting_chunk_ids)
        return tuple(source_ids)

    @staticmethod
    def _sentences(value: str) -> tuple[str, ...]:
        """Split text conservatively while retaining original factual wording."""
        return tuple(
            sentence.strip()
            for sentence in _SENTENCE_SPLIT_PATTERN.split(value.strip())
            if sentence.strip()
        )

    @staticmethod
    def _tokens(value: str) -> frozenset[str]:
        """Return small normalized lexical tokens for deterministic routing."""
        return frozenset(
            token
            for raw_token in _TOKEN_PATTERN.findall(value)
            if (token := ReportComposer._normalized_token(raw_token))
        )

    @staticmethod
    def _content_tokens(value: str) -> frozenset[str]:
        """Return non-stopword tokens for bounded duplicate comparisons."""
        return frozenset(
            token
            for token in ReportComposer._tokens(value)
            if token not in _STOP_TOKENS
        )

    @staticmethod
    def _normalized_text(value: str) -> str:
        """Normalize lexical comparison only; never mutate rendered source text."""
        return " ".join(
            token
            for raw_token in _TOKEN_PATTERN.findall(value)
            if (token := ReportComposer._normalized_token(raw_token))
        )

    @staticmethod
    def _normalized_token(value: str) -> str:
        """Drop sentence punctuation while preserving internal technical syntax."""
        return value.casefold().rstrip(".,;:!?")

    @staticmethod
    def _strip_terminal_punctuation(value: str) -> str:
        """Normalize only sentence-ending punctuation for structural checks."""
        return value.strip().rstrip(".,;:!?")

    @staticmethod
    def _normalized_reference_key(value: str) -> str:
        """Dedupe reference text without changing its first display spelling."""
        return _SPACE_PATTERN.sub(" ", value).strip().casefold()
