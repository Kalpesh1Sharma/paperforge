"""Tests for the deterministic research report foundation."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.knowledge import KnowledgeObject
from app.reports import (
    ConsolidatedDefinition,
    ConsolidatedReference,
    EnhancedResearchReport,
    EnrichedFinding,
    EntityGroup,
    IntelligentTimelineEvent,
    Finding,
    InvalidResearchReportError,
    MarkdownRenderer,
    ReportRenderingError,
    ReportSection,
    ReportSynthesisError,
    ResearchReport,
    ResearchSynthesizer,
    ReportIntelligence,
    NormalizedEntity,
    SynthesisSourceEvidence,
    SynthesizedSection,
    SynthesisMetadata,
    TimelineEvent,
)
from app.reports.presentation import EnhancedReportRenderContext
from app.reports.composer import ReportComposer
from app.reports.presentation_models import (
    AppendixGroup,
    EvidenceTable,
    HiddenPresentationData,
    InsightCard,
    PRESENTATION_SECTION_SPECS,
    PresentationEvidence,
)


def _knowledge(
    chunk_id: UUID,
    *,
    entities: tuple[str, ...] = (),
    facts: tuple[str, ...] = (),
    definitions: tuple[str, ...] = (),
    metrics: tuple[str, ...] = (),
    dates: tuple[str, ...] = (),
    references: tuple[str, ...] = (),
) -> KnowledgeObject:
    return KnowledgeObject(
        chunk_id=chunk_id,
        entities=entities,
        facts=facts,
        definitions=definitions,
        metrics=metrics,
        dates=dates,
        references=references,
        confidence=1.0,
    )


def _report(
    *,
    findings: tuple[Finding, ...] = (),
    important_entities: tuple[str, ...] = (),
    important_definitions: tuple[str, ...] = (),
    important_metrics: tuple[str, ...] = (),
    timeline: tuple[TimelineEvent, ...] = (),
    references: tuple[str, ...] = (),
    sections: tuple[ReportSection, ...] = (),
) -> ResearchReport:
    return ResearchReport(
        title="Research Report",
        executive_summary="Summary.",
        findings=findings,
        important_entities=important_entities,
        important_definitions=important_definitions,
        important_metrics=important_metrics,
        timeline=timeline,
        references=references,
        sections=sections,
    )


def _assert_markdown_presentation_contract(markdown: str) -> None:
    """Assert the fixed publication hierarchy projected from the composer."""
    assert markdown.startswith("# Research Report\n\n")
    assert "*PaperForge Research Report - v0.9.0*" in markdown
    assert "## Cover Page" not in markdown
    assert "Prepared from document: **Not available**" in markdown
    assert "Prepared by PaperForge" in markdown
    assert "| Publication detail | Value |" in markdown
    assert "## Table of Contents" in markdown

    section_markers = tuple(
        f"## {heading}" for _, heading, _ in PRESENTATION_SECTION_SPECS
    )
    positions = tuple(markdown.index(marker) for marker in section_markers)

    assert positions == tuple(sorted(positions))
    for index, (_, heading, anchor_id) in enumerate(
        PRESENTATION_SECTION_SPECS,
        start=1,
    ):
        assert f"{index}. [{heading}](#{anchor_id})" in markdown


def test_report_models_are_strict_immutable_and_forbid_extra_fields() -> None:
    chunk_id = uuid4()

    with pytest.raises(ValidationError):
        Finding(
            title="Finding 1",
            description="A fact.",
            supporting_chunk_ids=(str(chunk_id),),
        )
    with pytest.raises(ValidationError):
        ReportSection(heading="Appendix", content="Notes", unexpected=True)
    with pytest.raises(ValidationError):
        ResearchReport(
            title="Research Report",
            executive_summary="Summary.",
            unexpected=True,
        )
    with pytest.raises(ValidationError):
        _report(important_entities=["PaperForge"])  # type: ignore[arg-type]

    report = _report(important_entities=("PaperForge",))
    with pytest.raises(ValidationError):
        report.title = "Changed"
    with pytest.raises(AttributeError):
        report.important_entities.append("Another")  # type: ignore[attr-defined]


def test_research_report_rejects_duplicate_entities_and_references() -> None:
    with pytest.raises(ValidationError, match="important_entities"):
        _report(important_entities=("PaperForge", "PaperForge"))
    with pytest.raises(ValidationError, match="references"):
        _report(references=("https://example.com", "https://example.com"))

    report = _report(references=("Reference B", "Reference A"))

    assert report.references == ("Reference B", "Reference A")


def test_synthesizer_handles_empty_input_deterministically() -> None:
    synthesizer = ResearchSynthesizer()

    first = synthesizer.synthesize(())
    second = synthesizer.synthesize(())

    assert first == second
    assert first.title == "Research Report"
    assert first.executive_summary == (
        "Research report generated from 0 extracted knowledge objects."
    )
    assert first.findings == ()
    assert first.important_entities == ()
    assert first.important_definitions == ()
    assert first.important_metrics == ()
    assert first.timeline == ()
    assert first.references == ()
    assert first.sections == ()


def test_synthesizer_builds_ordered_report_and_preserves_inputs() -> None:
    first_chunk_id = uuid4()
    second_chunk_id = uuid4()
    first = _knowledge(
        first_chunk_id,
        entities=("PaperForge", "Shared Entity"),
        facts=("First fact.", "Repeated fact."),
        definitions=("Definition one",),
        metrics=("95%",),
        dates=("2025",),
        references=("Reference A",),
    )
    second = _knowledge(
        second_chunk_id,
        entities=("Shared Entity", "Research Team"),
        facts=("Repeated fact.", "Second fact."),
        definitions=("Definition one", "Definition two"),
        metrics=("95%", "10 kg"),
        dates=("2025", "2026-07-29"),
        references=("Reference A", "Reference B"),
    )
    inputs = (first, second)
    before = tuple(item.model_dump(mode="python") for item in inputs)

    report = ResearchSynthesizer().synthesize(inputs)

    assert tuple(item.model_dump(mode="python") for item in inputs) == before
    assert report.executive_summary == (
        "Research report generated from 2 extracted knowledge objects."
    )
    assert report.important_entities == (
        "PaperForge",
        "Shared Entity",
        "Research Team",
    )
    assert report.important_definitions == ("Definition one", "Definition two")
    assert report.important_metrics == ("95%", "10 kg")
    assert report.references == ("Reference A", "Reference B")
    assert report.findings == (
        Finding(
            title="Finding 1",
            description="First fact.",
            supporting_chunk_ids=(first_chunk_id,),
        ),
        Finding(
            title="Finding 2",
            description="Repeated fact.",
            supporting_chunk_ids=(first_chunk_id,),
        ),
        Finding(
            title="Finding 3",
            description="Repeated fact.",
            supporting_chunk_ids=(second_chunk_id,),
        ),
        Finding(
            title="Finding 4",
            description="Second fact.",
            supporting_chunk_ids=(second_chunk_id,),
        ),
    )
    assert report.timeline == (
        TimelineEvent(
            date="2025",
            description="Extracted date: 2025.",
            supporting_chunk_ids=(first_chunk_id,),
        ),
        TimelineEvent(
            date="2025",
            description="Extracted date: 2025.",
            supporting_chunk_ids=(second_chunk_id,),
        ),
        TimelineEvent(
            date="2026-07-29",
            description="Extracted date: 2026-07-29.",
            supporting_chunk_ids=(second_chunk_id,),
        ),
    )
    assert report.sections == ()


def test_synthesizer_output_is_deterministic_for_single_object() -> None:
    knowledge = _knowledge(
        uuid4(),
        entities=("PaperForge",),
        facts=("The result is reproducible.",),
        dates=("July 2026",),
    )
    synthesizer = ResearchSynthesizer()

    first = synthesizer.synthesize((knowledge,))
    second = synthesizer.synthesize((knowledge,))

    assert first == second
    assert first.findings[0].supporting_chunk_ids == (knowledge.chunk_id,)
    assert first.timeline[0].supporting_chunk_ids == (knowledge.chunk_id,)


def test_synthesizer_rejects_invalid_tuple_and_corrupted_knowledge() -> None:
    synthesizer = ResearchSynthesizer()
    corrupted = KnowledgeObject.model_construct(
        chunk_id=uuid4(),
        entities=["PaperForge"],
        facts=(),
        definitions=(),
        metrics=(),
        dates=(),
        references=(),
        confidence=1.0,
    )

    with pytest.raises(ReportSynthesisError, match="tuple"):
        synthesizer.synthesize([])  # type: ignore[arg-type]
    with pytest.raises(ReportSynthesisError, match="entities"):
        synthesizer.synthesize((corrupted,))


def test_renderer_has_exact_stable_markdown_layout() -> None:
    chunk_id = uuid4()
    report = _report(
        findings=(
            Finding(
                title="Finding 1",
                description="A fact.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
        important_entities=("PaperForge",),
        important_definitions=("Evidence means support.",),
        important_metrics=("95%",),
        timeline=(
            TimelineEvent(
                date="2026-07-29",
                description="Extracted date: 2026-07-29.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
        references=("https://example.com",),
        sections=(ReportSection(heading="Appendix", content="Additional notes."),),
    )
    renderer = MarkdownRenderer()

    first = renderer.render(report)
    second = renderer.render(report)

    assert first == second
    assert first == (
        "# Research Report\n\n"
        "## Executive Summary\n\n"
        "Summary.\n\n"
        "## Key Findings\n\n"
        "- **Finding 1**: A fact.\n\n"
        "## Important Entities\n\n"
        "- PaperForge\n\n"
        "## Definitions\n\n"
        "- Evidence means support.\n\n"
        "## Metrics\n\n"
        "- 95%\n\n"
        "## Timeline\n\n"
        "- **2026-07-29**: Extracted date: 2026-07-29.\n\n"
        "## References\n\n"
        "- https://example.com\n\n"
        "## Appendix\n\n"
        "Additional notes.\n"
    )


def test_renderer_renders_empty_collections_and_rejects_corruption() -> None:
    renderer = MarkdownRenderer()
    empty_report = ResearchSynthesizer().synthesize(())
    corrupted = ResearchReport.model_construct(
        title="Research Report",
        executive_summary="Summary.",
        findings=(),
        important_entities=("Duplicate", "Duplicate"),
        important_definitions=(),
        important_metrics=(),
        timeline=(),
        references=(),
        sections=(),
    )

    markdown = renderer.render(empty_report)

    assert markdown.startswith("# Research Report\n\n## Executive Summary\n\n")
    assert "## Key Findings\n\n## Important Entities" in markdown
    assert markdown.endswith("## References\n")
    with pytest.raises(InvalidResearchReportError, match="important_entities"):
        renderer.render(corrupted)


def test_renderer_wraps_unexpected_rendering_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_render(
        _: type[MarkdownRenderer],
        __: ResearchReport,
    ) -> str:
        raise RuntimeError("rendering failure")

    monkeypatch.setattr(
        MarkdownRenderer,
        "_render_report",
        classmethod(fail_render),
    )

    with pytest.raises(ReportRenderingError):
        MarkdownRenderer().render(_report())


def test_renderer_renders_enhanced_overlay_without_changing_base_rendering() -> None:
    chunk_id = uuid4()
    base_report = _report(
        findings=(
            Finding(
                title="Finding 1",
                description="Deterministic source fact.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
        important_entities=("PaperForge",),
        important_definitions=("Evidence means support.",),
        important_metrics=("Source confidence: 95%",),
        references=("https://example.com",),
    )
    enhanced_report = EnhancedResearchReport(
        base_report=base_report,
        executive_summary=(
            "Enhanced summary paragraph one.\n\n"
            "Enhanced summary paragraph two."
        ),
        findings=(
            Finding(
                title="Grouped Finding",
                description="Enhanced grounded finding.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
        sections=(
            SynthesizedSection(
                heading="Professional Experience",
                content="Enhanced grounded section.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        ),
    )
    renderer = MarkdownRenderer()
    presentation = ReportComposer().compose(enhanced_report)

    deterministic_markdown = renderer.render(base_report)
    enhanced_markdown = renderer.render_enhanced(enhanced_report)

    assert "Summary." in deterministic_markdown
    assert "Deterministic source fact." in deterministic_markdown
    assert enhanced_markdown == renderer.render_presentation(presentation)
    _assert_markdown_presentation_contract(enhanced_markdown)
    assert "Enhanced summary paragraph one." in enhanced_markdown
    assert "Enhanced summary paragraph two." in enhanced_markdown
    assert "Grouped Finding" in enhanced_markdown
    assert "Deterministic source fact." not in enhanced_markdown
    assert "PaperForge" in enhanced_markdown
    assert "Evidence means support." in enhanced_markdown
    assert "95%" in enhanced_markdown
    assert "https://example.com" in enhanced_markdown
    assert "[Source 1]" in enhanced_markdown
    assert str(chunk_id) not in enhanced_markdown
    assert "### General" in enhanced_markdown
    assert "Professional Experience" in enhanced_markdown
    assert "Enhanced grounded section." in enhanced_markdown
    assert "## Appendix" in enhanced_markdown
    assert "### Supporting Statistics" in enhanced_markdown
    assert "Composition Details" in enhanced_markdown


def test_enhanced_renderer_accepts_a_nonblank_fallback_summary() -> None:
    """Markdown presentation is provider-agnostic for valid overlays."""
    chunk_id = uuid4()
    base_report = _report(
        findings=(
            Finding(
                title="Finding 1",
                description="Deterministic source fact.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
    )
    fallback = EnhancedResearchReport(
        base_report=base_report,
        executive_summary="Deterministic fallback summary.",
        findings=base_report.findings,
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="fallback",
            model=None,
            elapsed_ms=0.0,
            successful=True,
            enhanced=False,
            fallback=True,
            reason="connection",
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=chunk_id,
                    confidence=1.0,
                    references=(),
                ),
            ),
        ),
    )

    markdown = MarkdownRenderer().render_enhanced(fallback)

    _assert_markdown_presentation_contract(markdown)
    assert "Deterministic fallback summary." in markdown
    assert "Deterministic source fact." in markdown
    assert "| Provider | fallback |" in markdown
    assert "| Model | Not applicable |" in markdown
    assert "Sources: Source 1" in markdown
    assert str(chunk_id) not in markdown


def test_enhanced_renderer_uses_publication_hierarchy_for_shared_presentation() -> None:
    """Composed Markdown reads as a report, while retaining source-backed data."""
    chunk_id = uuid4()
    base_report = _report(
        findings=(
            Finding(
                title="Latency benchmark results",
                description="The source records a latency benchmark improvement.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
        timeline=(
            TimelineEvent(
                date="2024",
                description="The benchmark was published in 2024.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
        references=("Publication source",),
    )
    enhanced = EnhancedResearchReport(
        base_report=base_report,
        executive_summary=(
            "The document reports a source-backed latency benchmark.\n\n"
            "The result is presented with supporting evidence."
        ),
        findings=base_report.findings,
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=chunk_id,
                    confidence=0.9,
                    references=("Publication source",),
                ),
            ),
        ),
        report_intelligence=ReportIntelligence(
            definitions=(
                ConsolidatedDefinition(
                    concept="Latency",
                    definition="Latency is the time required to receive a response.",
                    related_concepts=("Performance",),
                    supporting_chunk_ids=(chunk_id,),
                    references=("Publication source",),
                    confidence=0.9,
                ),
            ),
            timeline=(
                IntelligentTimelineEvent(
                    date="2024",
                    description="The benchmark was published in 2024.",
                    supporting_chunk_ids=(chunk_id,),
                    references=("Publication source",),
                    confidence=0.9,
                ),
            ),
            findings=(
                EnrichedFinding(
                    source_kind="finding",
                    source_index=0,
                    title="Latency benchmark results",
                    summary="The source records a latency benchmark improvement.",
                    supporting_chunk_ids=(chunk_id,),
                    references=("Publication source",),
                    confidence=0.9,
                    importance="high",
                ),
            ),
            references=(
                ConsolidatedReference(
                    reference="Publication source",
                    supporting_chunk_ids=(chunk_id,),
                ),
            ),
        ),
    )
    before = enhanced.model_dump(mode="python")
    presentation = ReportComposer().compose(enhanced)

    markdown = MarkdownRenderer().render_presentation(presentation)

    assert enhanced.model_dump(mode="python") == before
    _assert_markdown_presentation_contract(markdown)
    cover, _ = markdown.split("## Table of Contents", maxsplit=1)
    assert f"| Research domain | {presentation.cover.domain} |" in cover
    assert "| Document type |" not in cover
    assert "| Knowledge objects analyzed |" not in cover
    assert "### Document Information" in markdown
    assert f"Domain: {presentation.cover.domain}." in markdown
    assert "Source type: Not available." not in markdown
    assert "#### Latency benchmark results" in markdown
    assert "#### Finding 1:" not in markdown
    assert "Importance: HIGH" in markdown
    assert "Confidence:" in markdown
    assert "Evidence: 1 source; Sources: Source 1" in markdown
    assert "### Latency" in markdown
    assert "**Why it matters:** Related finding: Latency benchmark results." in markdown
    assert "**Related concepts:** Performance" in markdown
    assert "### 2024" in markdown
    assert "### Table 1. Compression Statistics" in markdown
    assert "### Table 2. Finding Importance" in markdown
    assert "### References\n\n1. Publication source [Source 1]" in markdown
    assert str(chunk_id) not in markdown


def test_enhanced_renderer_uses_optional_intelligence_without_scores() -> None:
    """Markdown maps enriched details by canonical position and hides raw IDs."""
    first_chunk_id = uuid4()
    second_chunk_id = uuid4()
    base_report = _report(
        findings=(
            Finding(
                title="Deterministic finding",
                description="The source records a latency improvement.",
                supporting_chunk_ids=(first_chunk_id, second_chunk_id),
            ),
        ),
        important_entities=("PaperForge",),
        important_definitions=("Latency means response delay.",),
        important_metrics=("30%",),
        timeline=(
            TimelineEvent(
                date="2026-07-29",
                description="A latency improvement was reported.",
                supporting_chunk_ids=(first_chunk_id,),
            ),
        ),
        references=("https://example.com/base",),
    )
    enhanced = EnhancedResearchReport(
        base_report=base_report,
        executive_summary="Refined summary.",
        findings=base_report.findings,
        appendix_findings=(
            Finding(
                title="Appendix source finding",
                description="A supporting implementation detail.",
                supporting_chunk_ids=(second_chunk_id,),
            ),
        ),
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=first_chunk_id,
                    confidence=0.9,
                    references=("https://example.com/first",),
                ),
                SynthesisSourceEvidence(
                    chunk_id=second_chunk_id,
                    confidence=0.8,
                    references=("https://example.com/second",),
                ),
            ),
        ),
        report_intelligence=ReportIntelligence(
            entity_groups=(
                EntityGroup(
                    category="Organizations",
                    entities=(
                        NormalizedEntity(
                            name="PaperForge",
                            aliases=("PF",),
                            supporting_chunk_ids=(first_chunk_id,),
                            references=("https://example.com/first",),
                            confidence=0.9,
                        ),
                    ),
                ),
            ),
            definitions=(
                ConsolidatedDefinition(
                    concept="Latency",
                    definition="Latency is the time before a response.",
                    related_concepts=("Performance",),
                    supporting_chunk_ids=(first_chunk_id,),
                    references=("https://example.com/first",),
                    confidence=0.84,
                ),
            ),
            timeline=(
                IntelligentTimelineEvent(
                    date="2026-07-29",
                    description="The document reports a latency improvement.",
                    supporting_chunk_ids=(first_chunk_id,),
                    references=("https://example.com/first",),
                    confidence=0.84,
                ),
            ),
            findings=(
                EnrichedFinding(
                    source_kind="finding",
                    source_index=0,
                    title="Performance improvement",
                    summary="The document reports a measured latency improvement.",
                    supporting_chunk_ids=(first_chunk_id, second_chunk_id),
                    references=("https://example.com/first",),
                    confidence=0.92,
                    importance="high",
                ),
                EnrichedFinding(
                    source_kind="appendix",
                    source_index=0,
                    title="Implementation context",
                    summary="The document includes a supporting implementation detail.",
                    supporting_chunk_ids=(second_chunk_id,),
                    references=("https://example.com/second",),
                    confidence=0.71,
                    importance="low",
                ),
            ),
            references=(
                ConsolidatedReference(
                    reference="https://example.com/consolidated",
                    supporting_chunk_ids=(first_chunk_id, second_chunk_id),
                ),
            ),
        ),
    )

    markdown = MarkdownRenderer().render_enhanced(enhanced)

    _assert_markdown_presentation_contract(markdown)
    assert "Performance improvement" in markdown
    assert "Implementation context" in markdown
    assert "Importance: HIGH" in markdown
    assert "Importance: LOW" in markdown
    assert "Confidence: 100%" in markdown
    assert "Confidence: 60%" in markdown
    assert "Evidence: 2 sources" in markdown
    assert "Organizations" in markdown
    assert "also known as: PF" in markdown
    assert "**Related concepts:** Performance" in markdown
    assert "https://example.com/consolidated [Source 1, Source 2]" in markdown
    assert "score" not in markdown.lower()
    assert str(first_chunk_id) not in markdown
    assert str(second_chunk_id) not in markdown


def test_enhanced_presentation_retains_overflow_entities_as_hidden_inventory() -> None:
    """The composer limits primary entities without rendering valid overflow."""
    chunk_ids = tuple(uuid4() for _ in range(9))
    entities = tuple(
        NormalizedEntity(
            name=f"Technology {index}",
            aliases=(f"Tech {index}",),
            supporting_chunk_ids=(chunk_id,),
            references=(f"https://example.com/reference/{index}",),
            confidence=0.8,
        )
        for index, chunk_id in enumerate(chunk_ids, start=1)
    )
    intelligence = ReportIntelligence(
        entity_groups=(
            EntityGroup(category="Technologies", entities=entities),
        ),
        references=tuple(
            ConsolidatedReference(
                reference=f"https://example.com/reference/{index}",
                supporting_chunk_ids=(chunk_id,),
            )
            for index, chunk_id in enumerate(chunk_ids, start=1)
        ),
    )
    enhanced = EnhancedResearchReport(
        base_report=_report(),
        executive_summary="Display context only.",
        findings=(),
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            source_evidence=tuple(
                SynthesisSourceEvidence(
                    chunk_id=chunk_id,
                    confidence=0.8,
                    references=(f"https://example.com/reference/{index}",),
                )
                for index, chunk_id in enumerate(chunk_ids, start=1)
            ),
        ),
        report_intelligence=intelligence,
    )

    context = EnhancedReportRenderContext.from_report(enhanced)
    presentation = ReportComposer().compose(enhanced)
    markdown = MarkdownRenderer().render_enhanced(enhanced)

    assert len(enhanced.report_intelligence.entity_groups[0].entities) == 9
    assert len(context.entity_groups[0].entities) == 9
    assert tuple(entity.name for entity in context.entity_groups[0].entities) == tuple(
        f"Technology {index}" for index in range(1, 10)
    )
    assert tuple(reference.reference for reference in context.references) == tuple(
        f"https://example.com/reference/{index}" for index in range(1, 10)
    )
    _assert_markdown_presentation_contract(markdown)
    assert presentation.hidden_content.entity_groups[0].category == "Technologies"
    assert tuple(
        entity.name
        for entity in presentation.hidden_content.entity_groups[0].entities
    ) == ("Technology 9",)
    assert "### Additional Entities" not in markdown
    assert "Technology 9" not in markdown
    assert "9. https://example.com/reference/9 [Source 9]" not in markdown
    assert all(
        group.heading != "Additional Entities"
        for group in next(
            section
            for section in presentation.sections
            if section.anchor_id == "appendix"
        ).appendix_groups
    )


def test_enhanced_presentation_groups_findings_and_calibrates_confidence() -> None:
    """Grouping and calibration are transient views over immutable source data."""
    first_chunk_id = uuid4()
    second_chunk_id = uuid4()
    base_report = _report(
        findings=(
            Finding(
                title="PDF was introduced in 1993",
                description="PDF was introduced in 1993 for document exchange.",
                supporting_chunk_ids=(first_chunk_id,),
            ),
            Finding(
                title="ISO standard defines PDF",
                description="The ISO standard defines interoperable PDF behavior.",
                supporting_chunk_ids=(second_chunk_id,),
            ),
        )
    )
    enhanced = EnhancedResearchReport(
        base_report=base_report,
        executive_summary="History and standards are described.",
        findings=base_report.findings,
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        ),
        report_intelligence=ReportIntelligence(
            findings=(
                EnrichedFinding(
                    source_kind="finding",
                    source_index=0,
                    title=base_report.findings[0].title,
                    summary=base_report.findings[0].description,
                    supporting_chunk_ids=(first_chunk_id,),
                    references=(),
                    confidence=0.65,
                    importance="medium",
                ),
                EnrichedFinding(
                    source_kind="finding",
                    source_index=1,
                    title=base_report.findings[1].title,
                    summary=base_report.findings[1].description,
                    supporting_chunk_ids=(second_chunk_id,),
                    references=("https://example.com/standard",),
                    confidence=0.95,
                    importance="high",
                ),
            ),
        ),
    )

    context = EnhancedReportRenderContext.from_report(enhanced)
    presentation = ReportComposer().compose(enhanced)
    markdown = MarkdownRenderer().render_enhanced(enhanced)
    first_label = context.findings[0].confidence_label
    second_label = context.findings[1].confidence_label

    assert tuple(group.heading for group in context.finding_groups) == (
        "History",
        "Standards",
    )
    assert tuple(finding.title for finding in context.findings) == tuple(
        finding.title for finding in enhanced.findings
    )
    assert not hasattr(enhanced.report_intelligence, "finding_groups")
    assert enhanced.report_intelligence.findings[0].confidence == 0.65
    assert enhanced.report_intelligence.findings[1].confidence == 0.95
    assert first_label is not None and second_label is not None
    assert 60 <= int(first_label.removesuffix("%")) <= 100
    assert 60 <= int(second_label.removesuffix("%")) <= 100
    assert int(first_label.removesuffix("%")) < int(second_label.removesuffix("%"))
    _assert_markdown_presentation_contract(markdown)
    assert "### Selected Insights" in markdown
    assert "PDF was introduced in 1993" in markdown
    assert "ISO standard defines PDF" in markdown
    key_insights = next(
        section
        for section in presentation.sections
        if section.anchor_id == "key-insights"
    )
    assert key_insights.finding_groups[0].heading == "Selected Insights"


def test_enhanced_presentation_uses_evidence_richness_for_equal_confidence() -> None:
    """Equal raw confidence is deterministically distinguished by provenance."""
    first_chunk_id = uuid4()
    second_chunk_id = uuid4()
    base_report = _report(
        findings=(
            Finding(
                title="Feature one",
                description="The document describes a feature.",
                supporting_chunk_ids=(first_chunk_id,),
            ),
            Finding(
                title="Feature two",
                description="The document describes another feature.",
                supporting_chunk_ids=(first_chunk_id, second_chunk_id),
            ),
        )
    )
    enhanced = EnhancedResearchReport(
        base_report=base_report,
        executive_summary="Two features are described.",
        findings=base_report.findings,
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        ),
        report_intelligence=ReportIntelligence(
            findings=(
                EnrichedFinding(
                    source_kind="finding",
                    source_index=0,
                    title=base_report.findings[0].title,
                    summary=base_report.findings[0].description,
                    supporting_chunk_ids=(first_chunk_id,),
                    references=(),
                    confidence=0.8,
                    importance="low",
                ),
                EnrichedFinding(
                    source_kind="finding",
                    source_index=1,
                    title=base_report.findings[1].title,
                    summary=base_report.findings[1].description,
                    supporting_chunk_ids=(first_chunk_id, second_chunk_id),
                    references=("https://example.com/evidence",),
                    confidence=0.8,
                    importance="medium",
                ),
            ),
        ),
    )

    context = EnhancedReportRenderContext.from_report(enhanced)

    weaker = context.findings[0].confidence_label
    richer = context.findings[1].confidence_label
    assert weaker is not None and richer is not None
    assert int(weaker.removesuffix("%")) < int(richer.removesuffix("%"))
    assert enhanced.report_intelligence.findings[0].confidence == 0.8
    assert enhanced.report_intelligence.findings[1].confidence == 0.8


def test_markdown_presentation_renders_visible_metrics_and_appendix_statistics_only() -> None:
    """Markdown formats visible tables without surfacing hidden presentation data."""
    enhanced = EnhancedResearchReport(
        base_report=_report(),
        executive_summary="A concise enhanced summary.",
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        ),
    )
    presentation = ReportComposer().compose(enhanced)
    metrics_table = EvidenceTable(
        title="Key Metrics",
        columns=("Metric", "Value"),
        rows=(("Total pages", "12"), ("Latency reduction", "35%")),
    )
    compression_table = EvidenceTable(
        title="Compression Statistics",
        columns=("Category", "Extracted", "Displayed", "Appendix", "Hidden"),
        rows=(("Findings", "20", "8", "5", "7"),),
    )
    supporting_statistics = EvidenceTable(
        title="Supporting Statistics",
        columns=("Measure", "Count"),
        rows=(("Duplicate findings", "2"),),
    )
    evidence_section = next(
        section for section in presentation.sections if section.key == "evidence-summary"
    )
    appendix_section = next(
        section for section in presentation.sections if section.key == "appendix"
    )
    hidden_finding = InsightCard(
        key="hidden-overflow-finding",
        title="Hidden overflow finding",
        summary="This must remain unavailable in the professional report.",
        evidence=PresentationEvidence(),
    )
    updated_evidence = evidence_section.model_copy(
        update={
            "evidence_tables": evidence_section.evidence_tables
            + (metrics_table, compression_table)
        }
    )
    updated_appendix = appendix_section.model_copy(
        update={
            "appendix_groups": appendix_section.appendix_groups
            + (
                AppendixGroup(
                    heading="Supporting Statistics",
                    evidence_tables=(supporting_statistics,),
                ),
            )
        }
    )
    updated_presentation = presentation.model_copy(
        update={
            "sections": tuple(
                updated_evidence
                if section.key == "evidence-summary"
                else updated_appendix
                if section.key == "appendix"
                else section
                for section in presentation.sections
            ),
            "hidden_content": HiddenPresentationData(
                findings=(hidden_finding,),
            ),
        }
    )

    markdown = MarkdownRenderer().render_presentation(updated_presentation)

    assert "### Table " in markdown and ". Key Metrics" in markdown
    assert "| Metric | Value |" in markdown
    assert "| Total pages | 12 |" in markdown
    assert ". Compression Statistics" in markdown
    assert "| Category | Extracted | Displayed | Appendix | Hidden |" in markdown
    assert "### Supporting Statistics" in markdown
    assert "#### Table 1. Supporting Statistics" in markdown
    assert "| Duplicate findings | 2 |" in markdown
    assert "Hidden overflow finding" not in markdown
