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
        important_metrics=("95%",),
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

    deterministic_markdown = renderer.render(base_report)
    enhanced_markdown = renderer.render_enhanced(enhanced_report)

    assert "Summary." in deterministic_markdown
    assert "Deterministic source fact." in deterministic_markdown
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
    assert "## Professional Experience" in enhanced_markdown
    assert "Enhanced grounded section." in enhanced_markdown
    assert "## Appendix" in enhanced_markdown
    assert "No additional findings." in enhanced_markdown


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

    assert "Deterministic fallback summary." in markdown
    assert "Deterministic source fact." in markdown
    assert "[Source 1]" in markdown
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

    assert "Performance improvement" in markdown
    assert "Implementation context" in markdown
    assert "Importance: HIGH" in markdown
    assert "Importance: LOW" in markdown
    assert "Confidence: 92%" in markdown
    assert "Evidence: 2 sources" in markdown
    assert "Organizations" in markdown
    assert "also known as: PF" in markdown
    assert "Related concepts: Performance" in markdown
    assert "https://example.com/consolidated [Source 1, Source 2]" in markdown
    assert "score" not in markdown.lower()
    assert str(first_chunk_id) not in markdown
    assert str(second_chunk_id) not in markdown
