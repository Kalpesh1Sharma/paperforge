"""Focused v0.8.7 coverage for bounded deterministic report composition."""

from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.reports import (
    CompressionStatistic,
    EnhancedResearchReport,
    Finding,
    HiddenPresentationData,
    InsightCard,
    MetricCard,
    PresentationBudget,
    PresentationEvidence,
    ReportComposer,
    ReportMode,
    ResearchReport,
    SynthesisMetadata,
    SynthesisSourceEvidence,
    TimelineEvent,
    SynthesizedSection,
)


_CHUNK_ID = UUID("11111111-1111-4111-8111-111111111111")


def _section(model: object, key: str):
    """Return one fixed composed section by its public stable key."""
    return next(section for section in model.sections if section.key == key)


def _finding_cards(section: object) -> tuple[InsightCard, ...]:
    """Flatten typed groups for concise cardinality assertions."""
    return tuple(card for group in section.finding_groups for card in group.findings)


def _appendix_findings(model: object) -> tuple[InsightCard, ...]:
    """Return every appendix finding without relying on group display order."""
    appendix = _section(model, "appendix")
    return tuple(card for group in appendix.appendix_groups for card in group.findings)


def _appendix_concepts(model: object) -> tuple[object, ...]:
    """Return every appendix concept without coupling to headings."""
    appendix = _section(model, "appendix")
    return tuple(card for group in appendix.appendix_groups for card in group.concepts)


def _dense_report(
    *,
    finding_count: int = 38,
    appendix_finding_count: int = 18,
    definition_count: int = 18,
    metric_count: int = 16,
    timeline_count: int = 14,
    reference_count: int = 12,
) -> EnhancedResearchReport:
    """Build meaningful overflow content with one valid source ledger entry."""
    findings = tuple(
        Finding(
            title=f"Architecture finding {index + 1}",
            description=(
                "The document records a distinct architecture result "
                f"{index + 1} with traceable supporting evidence."
            ),
            supporting_chunk_ids=(_CHUNK_ID,),
        )
        for index in range(finding_count)
    )
    appendix_findings = tuple(
        Finding(
            title=f"Secondary finding {index + 1}",
            description=(
                "The document records a distinct secondary result "
                f"{index + 1} with traceable supporting evidence."
            ),
            supporting_chunk_ids=(_CHUNK_ID,),
        )
        for index in range(appendix_finding_count)
    )
    definitions = tuple(
        f"Concept {index + 1}: A complete, source-backed technical definition "
        f"for concept {index + 1}."
        for index in range(definition_count)
    )
    timeline = tuple(
        TimelineEvent(
            date=str(2000 + index),
            description=(
                f"The document records a dated technical milestone {index + 1}."
            ),
            supporting_chunk_ids=(_CHUNK_ID,),
        )
        for index in range(timeline_count)
    )
    summary = "\n\n".join(
        f"Summary paragraph {index + 1} presents a distinct report topic."
        for index in range(7)
    )
    return EnhancedResearchReport(
        base_report=ResearchReport(
            title="Bounded Composition Report",
            executive_summary="Canonical deterministic report content.",
            important_entities=tuple(
                f"Technology {index + 1}" for index in range(12)
            ),
            important_definitions=definitions,
            important_metrics=tuple(
                f"Reported metric {index + 1}: {index + 1}" for index in range(metric_count)
            ),
            timeline=timeline,
            references=tuple(
                f"https://example.com/reference-{index + 1}"
                for index in range(reference_count)
            ),
        ),
        executive_summary=summary,
        findings=findings,
        appendix_findings=appendix_findings,
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=_CHUNK_ID,
                    confidence=0.82,
                    references=("https://example.com/source",),
                ),
            ),
        ),
    )


def test_named_budget_presets_are_strict_frozen_and_professional_is_fixed() -> None:
    """Modes expose immutable named budgets with the published default contract."""
    professional = PresentationBudget.for_mode(ReportMode.PROFESSIONAL)
    executive = PresentationBudget.for_mode(ReportMode.EXECUTIVE)
    technical = PresentationBudget.for_mode(ReportMode.TECHNICAL)
    full = PresentationBudget.for_mode(ReportMode.FULL)

    assert professional.abstract_word_limit == 180
    assert professional.executive_summary_paragraph_limit == 5
    assert professional.key_insights_limit == 8
    assert professional.technical_analysis_limit == 8
    assert professional.timeline_limit == 10
    assert professional.primary_concepts_limit == 6
    assert professional.entities_per_category_limit == 8
    assert professional.evidence_table_row_limit == 10
    assert professional.metrics_limit == 12
    assert professional.appendix_findings_limit == 15
    assert professional.appendix_concepts_limit == 10
    assert professional.primary_references_limit == 6

    assert executive.key_insights_limit < professional.key_insights_limit
    assert technical.technical_analysis_limit > professional.technical_analysis_limit
    assert full.abstract_word_limit == 250
    assert full.key_insights_limit is None
    assert full.primary_references_limit is None

    with pytest.raises(ValidationError):
        professional.key_insights_limit = 1  # type: ignore[misc]
    invalid_payload = professional.model_dump(mode="python")
    invalid_payload["unknown_limit"] = 1
    with pytest.raises(ValidationError):
        PresentationBudget.model_validate(invalid_payload)


def test_hidden_content_metric_and_compression_models_preserve_provenance() -> None:
    """Hidden overflow stays immutable and statistics account for every item."""
    evidence = PresentationEvidence(
        supporting_chunk_ids=(_CHUNK_ID,),
        source_labels=("Source 1",),
        references=("https://example.com/source",),
        confidence=0.82,
        source_count=1,
    )
    finding = InsightCard(
        key="finding-1",
        title="Bounded finding",
        summary="The source contains a bounded finding.",
        importance="HIGH",
        evidence=evidence,
    )
    metric = MetricCard(
        key="metric-1",
        label="Total pages",
        value="20",
        evidence=PresentationEvidence(),
    )
    hidden = HiddenPresentationData(findings=(finding,), metrics=(metric,))
    statistic = CompressionStatistic(
        category="findings",
        extracted=10,
        displayed=3,
        moved_to_appendix=2,
        hidden=3,
        deduplicated=1,
        artifact_rejected=1,
    )

    assert hidden.findings[0].evidence.supporting_chunk_ids == (_CHUNK_ID,)
    assert hidden.metrics[0].evidence.supporting_chunk_ids == ()
    assert metric.evidence.supporting_chunk_ids == ()
    assert statistic.extracted == 10

    with pytest.raises(ValidationError):
        hidden.findings = ()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        MetricCard(
            key="metric-2",
            label="Invalid",
            value="1",
            evidence=PresentationEvidence(),
            unexpected="generated",
        )
    with pytest.raises(ValidationError):
        CompressionStatistic(
            category="findings",
            extracted=3,
            displayed=1,
            moved_to_appendix=1,
            hidden=0,
            deduplicated=0,
            artifact_rejected=0,
        )


def test_professional_composition_preserves_overflow_and_accounts_for_compression() -> None:
    """Professional mode limits visible content without deleting source evidence."""
    report = _dense_report()
    before = deepcopy(report.model_dump(mode="python"))

    first = ReportComposer().compose(report)
    second = ReportComposer(mode=ReportMode.PROFESSIONAL).compose(report)
    budget = PresentationBudget.for_mode(ReportMode.PROFESSIONAL)

    assert first == second
    assert first.mode is ReportMode.PROFESSIONAL
    assert first.budget == budget
    assert len(_section(first, "abstract").intro[0].split()) <= budget.abstract_word_limit
    assert (
        len(_section(first, "executive-summary").intro)
        <= budget.executive_summary_paragraph_limit
    )
    assert len(_finding_cards(_section(first, "key-insights"))) <= budget.key_insights_limit
    assert (
        len(_finding_cards(_section(first, "technical-analysis")))
        <= budget.technical_analysis_limit
    )
    assert len(_section(first, "historical-timeline").timeline) <= budget.timeline_limit
    assert len(_section(first, "important-concepts").concepts) <= budget.primary_concepts_limit
    assert all(
        len(group.entities) <= budget.entities_per_category_limit
        for group in _section(first, "document-overview").entity_groups
    )
    assert len(_appendix_findings(first)) <= budget.appendix_findings_limit
    assert len(_appendix_concepts(first)) <= budget.appendix_concepts_limit
    assert len(_section(first, "evidence-summary").references) <= budget.primary_references_limit
    assert all(
        len(table.rows) <= budget.evidence_table_row_limit
        for table in _section(first, "evidence-summary").evidence_tables
        if table.title != "Key Metrics"
    )
    assert len(
        next(
            table
            for table in _section(first, "evidence-summary").evidence_tables
            if table.title == "Key Metrics"
        ).rows
    ) <= budget.metrics_limit

    assert first.hidden_content.findings
    assert first.hidden_content.metrics
    assert all(
        card.evidence.supporting_chunk_ids == (_CHUNK_ID,)
        for card in first.hidden_content.findings
    )
    assert all(
        statistic.extracted
        == statistic.displayed
        + statistic.moved_to_appendix
        + statistic.hidden
        + statistic.deduplicated
        + statistic.artifact_rejected
        for statistic in first.compression_statistics
    )
    assert any(statistic.hidden for statistic in first.compression_statistics)
    assert report.model_dump(mode="python") == before


def test_modes_change_visibility_without_changing_the_composer_signature() -> None:
    """Constructor-selected modes retain deterministic content and bounded views."""
    report = _dense_report(
        finding_count=24,
        appendix_finding_count=0,
        definition_count=0,
        metric_count=0,
        timeline_count=0,
        reference_count=0,
    )

    executive = ReportComposer(mode=ReportMode.EXECUTIVE).compose(report)
    technical = ReportComposer(mode=ReportMode.TECHNICAL).compose(report)
    full = ReportComposer(mode=ReportMode.FULL).compose(report)

    assert executive.mode is ReportMode.EXECUTIVE
    assert technical.mode is ReportMode.TECHNICAL
    assert full.mode is ReportMode.FULL
    assert len(_finding_cards(_section(executive, "key-insights"))) <= 5
    assert len(_finding_cards(_section(executive, "technical-analysis"))) <= 3
    assert len(_finding_cards(_section(technical, "key-insights"))) <= 8
    assert len(_finding_cards(_section(technical, "technical-analysis"))) <= 16
    assert not full.hidden_content.findings
    assert not full.hidden_content.metrics


def test_composer_rejects_duplicates_and_parser_artifacts_from_all_presentation_content() -> None:
    """Artifact and duplicate suppression is visible in compression accounting."""
    source = _dense_report(
        finding_count=0,
        appendix_finding_count=0,
        definition_count=0,
        metric_count=0,
        timeline_count=0,
        reference_count=0,
    )
    duplicate = Finding(
        title="PDF standard release",
        description="The document records the PDF standard release in 2008.",
        supporting_chunk_ids=(_CHUNK_ID,),
    )
    artifact = Finding(
        title="4.1 Simple Data Table",
        description="4.1",
        supporting_chunk_ids=(_CHUNK_ID,),
    )
    report = source.model_copy(
        update={"findings": (duplicate, duplicate, artifact)}
    )

    model = ReportComposer().compose(report)
    all_visible = _finding_cards(_section(model, "key-insights")) + _finding_cards(
        _section(model, "technical-analysis")
    ) + _appendix_findings(model)
    finding_statistic = next(
        statistic
        for statistic in model.compression_statistics
        if statistic.category.casefold() == "findings"
    )

    assert sum(card.title == duplicate.title for card in all_visible) == 1
    assert all("4.1 Simple Data Table" != card.title for card in all_visible)
    assert all("4.1 Simple Data Table" != card.title for card in model.hidden_content.findings)
    assert finding_statistic.deduplicated >= 1
    assert finding_statistic.artifact_rejected >= 1


def test_composer_keeps_unlabelled_metrics_hidden_and_counted() -> None:
    """Bare values remain available off-page without an invented label."""
    report = _dense_report(
        finding_count=0,
        appendix_finding_count=0,
        definition_count=0,
        metric_count=0,
        timeline_count=0,
        reference_count=0,
    ).model_copy(
        update={
            "base_report": ResearchReport(
                title="Metric retention",
                executive_summary="Metric-focused deterministic report.",
                important_metrics=(
                    "95%",
                    "95%",
                    "Latency reduction: 25%",
                ),
            )
        }
    )

    model = ReportComposer().compose(report)
    metrics_section = _section(model, "evidence-summary")
    statistics = next(
        statistic
        for statistic in model.compression_statistics
        if statistic.category == "Metrics"
    )

    assert model.hidden_content.unlabeled_metrics == ("95%",)
    assert model.hidden_content.metrics == ()
    assert any(
        table.title == "Key Metrics"
        and table.rows == (("Latency reduction", "25%"),)
        for table in metrics_section.evidence_tables
    )
    assert statistics.extracted == 3
    assert statistics.displayed == 1
    assert statistics.hidden == 1
    assert statistics.deduplicated == 1
    assert statistics.artifact_rejected == 0


def test_composer_does_not_merge_distinct_events_with_a_shared_subject() -> None:
    """Narrow event matching cannot collapse facts from different years."""
    source = _dense_report(
        finding_count=0,
        appendix_finding_count=0,
        definition_count=0,
        metric_count=0,
        timeline_count=0,
        reference_count=0,
    )
    report = source.model_copy(
        update={
            "findings": (
                Finding(
                    title="Adobe introduced PDF in 1993",
                    description="Adobe introduced PDF in 1993 for document exchange.",
                    supporting_chunk_ids=(_CHUNK_ID,),
                ),
                Finding(
                    title="Another company introduced PDF in 2001",
                    description="Another company introduced PDF in 2001 for archiving.",
                    supporting_chunk_ids=(_CHUNK_ID,),
                ),
            )
        }
    )

    model = ReportComposer().compose(report)
    cards = _finding_cards(_section(model, "key-insights"))
    finding_statistic = next(
        statistic
        for statistic in model.compression_statistics
        if statistic.category == "Findings"
    )

    assert tuple(card.title for card in cards) == (
        "Adobe introduced PDF in 1993",
        "Another company introduced PDF in 2001",
    )
    assert finding_statistic.deduplicated == 0


def test_zero_limits_suppress_visible_allocations_without_losing_inventory() -> None:
    """Every finite presentation limit may intentionally be zero."""
    report = _dense_report(
        finding_count=2,
        appendix_finding_count=0,
        definition_count=0,
        metric_count=1,
        timeline_count=0,
        reference_count=0,
    )
    budget = PresentationBudget(
        abstract_word_limit=0,
        executive_summary_paragraph_limit=0,
        key_insights_limit=0,
        technical_analysis_limit=0,
        timeline_limit=0,
        primary_concepts_limit=0,
        entities_per_category_limit=0,
        metrics_limit=0,
        appendix_findings_limit=0,
        appendix_concepts_limit=0,
        primary_references_limit=0,
        evidence_table_row_limit=0,
    )

    model = ReportComposer(mode=ReportMode.EXECUTIVE, budget=budget).compose(report)

    assert model.mode is ReportMode.EXECUTIVE
    assert model.budget == budget
    assert _section(model, "abstract").intro == ()
    assert _section(model, "executive-summary").intro == ()
    assert _finding_cards(_section(model, "key-insights")) == ()
    assert _finding_cards(_section(model, "technical-analysis")) == ()
    assert _section(model, "evidence-summary").evidence_tables == ()
    assert model.hidden_content.findings


def test_composer_curates_artifacts_and_duplicate_supported_sections_once() -> None:
    """All curation inputs share one deterministic suppression pass."""
    report = EnhancedResearchReport(
        base_report=ResearchReport(
            title="Curation coverage",
            executive_summary="Canonical content.",
            important_entities=("PaperForge", "paperforge", "Page 2."),
            important_definitions=(
                "4.1.",
                "Evidence: Information that supports a source-backed claim.",
            ),
        ),
        executive_summary="A concise enhanced summary.",
        findings=(
            Finding(
                title="Single supported fact",
                description="The document records one supported fact.",
                supporting_chunk_ids=(_CHUNK_ID,),
            ),
        ),
        sections=(
            SynthesizedSection(
                heading="Duplicate section",
                content="The document records one supported fact.",
                supporting_chunk_ids=(_CHUNK_ID,),
            ),
        ),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=_CHUNK_ID,
                    confidence=0.8,
                    references=(),
                ),
            ),
        ),
    )

    model = ReportComposer().compose(report)
    overview = _section(model, "document-overview")
    concepts = _section(model, "important-concepts")
    key_insights = _finding_cards(_section(model, "key-insights"))
    technical = _finding_cards(_section(model, "technical-analysis"))
    statistics = {
        statistic.category: statistic for statistic in model.compression_statistics
    }

    assert tuple(entity.name for entity in overview.entity_groups[0].entities) == (
        "PaperForge",
    )
    assert tuple(concept.concept for concept in concepts.concepts) == (
        "Evidence: Information that supports a source-backed claim.",
    )
    assert tuple(card.title for card in key_insights) == ("Single supported fact",)
    assert technical == ()
    assert statistics["Entities"].deduplicated == 1
    assert statistics["Entities"].artifact_rejected == 1
    assert statistics["Concepts"].artifact_rejected == 1
    assert statistics["Findings"].deduplicated == 1


def test_event_and_terminal_punctuation_deduplication_are_conservative() -> None:
    """Page references do not collide with page counts or punctuated facts."""
    source = _dense_report(
        finding_count=0,
        appendix_finding_count=0,
        definition_count=0,
        metric_count=0,
        timeline_count=0,
        reference_count=0,
    )
    report = source.model_copy(
        update={
            "findings": (
                Finding(
                    title="PDF release",
                    description="PDF was released in 2008.",
                    supporting_chunk_ids=(_CHUNK_ID,),
                ),
                Finding(
                    title="PDF release restated",
                    description="PDF was released in 2008",
                    supporting_chunk_ids=(_CHUNK_ID,),
                ),
                Finding(
                    title="Page explanation",
                    description="Page 5 explains the security architecture",
                    supporting_chunk_ids=(_CHUNK_ID,),
                ),
                Finding(
                    title="Document length",
                    description="The document contains 5 pages",
                    supporting_chunk_ids=(_CHUNK_ID,),
                ),
            )
        }
    )

    model = ReportComposer().compose(report)
    cards = _finding_cards(_section(model, "key-insights"))
    finding_statistic = next(
        statistic
        for statistic in model.compression_statistics
        if statistic.category == "Findings"
    )

    assert tuple(card.title for card in cards) == (
        "PDF release",
        "Page explanation",
        "Document length",
    )
    assert finding_statistic.deduplicated == 1
