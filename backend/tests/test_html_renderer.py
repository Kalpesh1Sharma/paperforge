"""Tests for deterministic standalone HTML rendering."""

from copy import deepcopy
from datetime import date
from uuid import UUID

import pytest

from app.reports import (
    ConsolidatedDefinition,
    ConsolidatedReference,
    EnhancedResearchReport,
    EnrichedFinding,
    EntityGroup,
    Finding,
    HTMLRenderer,
    IntelligentTimelineEvent,
    InvalidResearchReportError,
    ReportRenderingError,
    ResearchReport,
    ReportIntelligence,
    NormalizedEntity,
    SynthesisMetadata,
    SynthesisSourceEvidence,
    SynthesizedSection,
    TimelineEvent,
)
from app.reports import html_renderer
from app.reports.composer import ReportComposer
from app.reports.presentation_models import (
    AppendixGroup,
    EvidenceTable,
    HiddenPresentationData,
    InsightCard,
    PRESENTATION_SECTION_SPECS,
    PresentationEvidence,
)
from app.models.parsed_document import ParsedDocument

_CHUNK_ID = UUID("12345678-1234-5678-1234-567812345678")
_SECOND_CHUNK_ID = UUID("87654321-4321-8765-4321-876543218765")


def _assert_html_presentation_contract(html: str) -> None:
    """Assert the fixed, composer-owned publication navigation and layout."""
    assert '<article id="report-content" class="publication-report"' in html
    assert '<header id="cover-page" class="cover-page"' in html
    assert '<nav id="table-of-contents" class="table-of-contents"' in html
    assert 'aria-label="Table of contents"' in html
    assert '<h2>Table of Contents</h2>' in html
    assert 'class="toc-leader" aria-hidden="true"' in html

    section_markers = tuple(
        f'<h2 id="{anchor_id}-heading">{heading}</h2>'
        for _, heading, anchor_id in PRESENTATION_SECTION_SPECS
    )
    positions = tuple(html.index(marker) for marker in section_markers)

    assert positions == tuple(sorted(positions))
    for _, heading, anchor_id in PRESENTATION_SECTION_SPECS:
        assert f'<a class="toc-link" href="#{anchor_id}">' in html
        assert f'<span class="toc-title">{heading}</span>' in html
        assert f'data-target="#{anchor_id}"' in html
        assert f'<section id="{anchor_id}"' in html
        assert f'aria-labelledby="{anchor_id}-heading"' in html


def _base_report(
    *,
    title: str = "Research Report",
    include_content: bool = True,
) -> ResearchReport:
    """Build a local immutable base-report fixture without network access."""
    if not include_content:
        return ResearchReport(
            title=title,
            executive_summary="Deterministic base summary.",
            findings=(),
            important_entities=(),
            important_definitions=(),
            important_metrics=(),
            timeline=(),
            references=(),
            sections=(),
        )

    return ResearchReport(
        title=title,
        executive_summary="Deterministic base summary.",
        findings=(
            Finding(
                title="Deterministic finding",
                description="The deterministic base finding is not rendered.",
                supporting_chunk_ids=(_CHUNK_ID,),
            ),
        ),
        important_entities=("PaperForge",),
        important_definitions=("Evidence means supporting information.",),
        important_metrics=("Source confidence: 95%",),
        timeline=(
            TimelineEvent(
                date="2026-07-29",
                description="Extracted date: 2026-07-29.",
                supporting_chunk_ids=(_CHUNK_ID,),
            ),
        ),
        references=("https://example.com/source",),
        sections=(),
    )


def _enhanced_report(
    *,
    base_report: ResearchReport | None = None,
    include_enhancements: bool = True,
) -> EnhancedResearchReport:
    """Build a valid immutable enhanced-report fixture for HTML rendering."""
    findings: tuple[Finding, ...]
    sections: tuple[SynthesizedSection, ...]
    if include_enhancements:
        findings = (
            Finding(
                title="Grouped backend work",
                description="The source documents API and middleware improvements.",
                supporting_chunk_ids=(_CHUNK_ID,),
            ),
        )
        sections = (
            SynthesizedSection(
                heading="Professional Experience",
                content="The documented work covers backend APIs and middleware.",
                supporting_chunk_ids=(_CHUNK_ID,),
            ),
        )
    else:
        findings = ()
        sections = ()

    return EnhancedResearchReport(
        base_report=base_report or _base_report(),
        executive_summary=(
            "The source describes backend engineering work focused on APIs.\n\n"
            "It records measurable performance improvements from that work."
        ),
        findings=findings,
        sections=sections,
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=_CHUNK_ID,
                    confidence=1.0,
                    references=("https://example.com/source",),
                ),
            ),
        ),
    )


def test_html_renderer_produces_stable_self_contained_document() -> None:
    """Repeated rendering emits a complete, standalone HTML document."""
    report = _enhanced_report()
    before = deepcopy(report.model_dump(mode="python"))
    renderer = HTMLRenderer()
    presentation = ReportComposer().compose(report)

    first = renderer.render(report)
    second = renderer.render(report)
    direct = renderer.render_presentation(presentation)

    assert first == second
    assert first == direct
    assert report.model_dump(mode="python") == before
    assert first.startswith("<!doctype html>\n<html lang=\"en\">")
    assert first.endswith("</html>\n")
    assert '<meta charset="utf-8">' in first
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in first
    assert '<style id="paperforge-report-styles">' in first
    assert '<style id="paperforge-print-styles" media="print">' in first
    assert "--paper: #fffefb;" in first
    assert "font-family: var(--serif);" in first
    assert "font-family: var(--sans);" in first
    assert "target-counter(attr(data-target), page);" in first
    assert "@page" in first
    assert "@page cover" in first
    assert "string-set: report-title content(text);" in first
    assert "content: \"PaperForge Research Report\";" in first
    assert "min-block-size: calc(11.69in - 1.44in);" in first
    assert "break-before: page;" in first
    assert ".publication-section--evidence-summary," in first
    assert ".publication-section--appendix {" in first
    assert first.count("break-before: page;") == 1
    assert "counter-reset: publication-reference;" in first
    assert "counter-increment: publication-reference;" in first
    assert "PaperForge v0.9.0" in first
    assert "Prepared by" in first and "Prepared from" in first
    assert "<figure class=\"evidence-table\">" in first
    assert "<figcaption" in first
    assert 'class="section-prose section-prose--abstract"' in first
    assert 'class="section-prose section-prose--executive-summary"' in first
    assert 'class="section-lead"' in first
    assert 'class="confidence-meter" aria-hidden="true"' in first
    assert 'class="status-badge">AI-enhanced</span>' in first
    assert "Source-backed observations are grouped here for focused review." in first
    assert "Source-derived entities retained for this category." in first
    assert "<dt>Generated</dt><dd>Not available</dd>" in first
    assert '<link rel="stylesheet"' not in first
    assert "<script" not in first.lower()
    assert "cdn" not in first.lower()
    assert "linear-gradient" not in first
    assert "box-shadow" not in first
    _assert_html_presentation_contract(first)


def test_html_renderer_renders_required_content_in_layout_order() -> None:
    """Composed enhanced content appears in the fixed presentation layout."""
    html = HTMLRenderer().render(_enhanced_report())

    _assert_html_presentation_contract(html)
    assert "The source describes backend engineering work focused on APIs." in html
    assert "Grouped backend work" in html
    assert "PaperForge" in html
    assert "Evidence means supporting information." in html
    assert "95%" in html
    assert "2026-07-29" in html
    assert "https://example.com/source" in html
    assert "The documented work covers backend APIs and middleware." in html
    assert "General" in html
    assert "Source 1" in html
    assert str(_CHUNK_ID) not in html


def test_html_renderer_uses_semantic_publication_metadata_and_toc_references() -> None:
    """The publication shell retains semantic cover data and page-ready TOC links."""
    source_text = "PaperForge publishes source-grounded research reports."
    source_document = ParsedDocument(
        filename="source.pdf",
        file_type="pdf",
        extracted_text=source_text,
        page_count=12,
        word_count=5,
        character_count=len(source_text),
        metadata={"title": "Publication Source"},
    )
    presentation = ReportComposer().compose(
        _enhanced_report(),
        source_document=source_document,
        generated_on=date(2026, 7, 30),
    )

    html = HTMLRenderer().render_presentation(presentation)

    assert '<header id="cover-page" class="cover-page"' in html
    assert "PaperForge v0.9.0" in html
    assert "<dt>Prepared by</dt><dd>PaperForge</dd>" in html
    assert "<dt>Prepared from</dt><dd>source.pdf</dd>" in html
    assert "<dt>Document type</dt><dd>PDF</dd>" in html
    assert "<dt>Total pages</dt><dd>12</dd>" in html
    assert '<time datetime="2026-07-30">2026-07-30</time>' in html
    assert '<nav id="table-of-contents" class="table-of-contents"' in html
    assert 'class="toc-page-reference" data-target="#abstract"' in html
    assert '<figure class="evidence-table">' in html
    assert '<caption class="visually-hidden">' in html


def test_html_renderer_uses_one_document_wide_reference_counter() -> None:
    """Publication references continue across primary and appendix lists."""
    html = HTMLRenderer().render(_enhanced_report())

    assert html.count("counter-reset: publication-reference;") == 1
    assert "counter-increment: publication-reference;" in html
    assert "counter-reset: references;" not in html


def test_html_renderer_escapes_dynamic_content() -> None:
    """Jinja autoescaping prevents hostile model strings from becoming markup."""
    hostile = "<script>alert('unsafe')</script>"
    base_report = ResearchReport(
        title=hostile,
        executive_summary="Base summary.",
        findings=(),
        important_entities=(hostile,),
        important_definitions=(),
        important_metrics=(),
        timeline=(),
        references=(),
        sections=(),
    )

    html = HTMLRenderer().render(_enhanced_report(base_report=base_report))

    assert hostile not in html
    assert "&lt;script&gt;alert(&#39;unsafe&#39;)&lt;/script&gt;" in html


def test_html_renderer_renders_empty_collections_with_accessible_empty_states() -> None:
    """Every required collection section remains visible when it has no content."""
    report = _enhanced_report(
        base_report=_base_report(include_content=False),
        include_enhancements=False,
    )

    html = HTMLRenderer().render(report)

    _assert_html_presentation_contract(html)
    # Evidence Summary always retains deterministic compression accounting.
    assert html.count("No information was extracted for this section.") == 4
    assert html.count('class="empty-state"') == 4
    assert "Compression Statistics" in html
    assert "Professional Experience" not in html


def test_html_renderer_accepts_any_nonblank_summary_and_rejects_corruption() -> None:
    """Presentation accepts fallback prose while still rejecting malformed models."""
    malformed = EnhancedResearchReport.model_construct(
        base_report=_base_report(),
        executive_summary="Only one paragraph.",
        findings=(),
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        ),
    )

    assert "Only one paragraph." in HTMLRenderer().render(malformed)
    with pytest.raises(InvalidResearchReportError, match="EnhancedResearchReport"):
        HTMLRenderer().render(object())  # type: ignore[arg-type]

    corrupted_base_report = ResearchReport.model_construct(
        title="Research Report",
        executive_summary="Base summary.",
        findings=(),
        important_entities=("Duplicate", "Duplicate"),
        important_definitions=(),
        important_metrics=(),
        timeline=(),
        references=(),
        sections=(),
    )
    nested_malformed = EnhancedResearchReport.model_construct(
        base_report=corrupted_base_report,
        executive_summary=(
            "First valid paragraph.\n\nSecond valid paragraph."
        ),
        findings=(),
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        ),
    )

    with pytest.raises(InvalidResearchReportError, match="structural"):
        HTMLRenderer().render(nested_malformed)


def test_html_renderer_renders_a_nullable_model_generically() -> None:
    """A fallback overlay renders through the provider-agnostic composition path."""
    fallback = EnhancedResearchReport(
        base_report=_base_report(include_content=False),
        executive_summary="Deterministic fallback summary.",
        findings=(),
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="fallback",
            model=None,
            elapsed_ms=0.0,
            successful=True,
            enhanced=False,
            fallback=True,
            reason="timeout",
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=_CHUNK_ID,
                    confidence=1.0,
                    references=(),
                ),
            ),
        ),
    )

    html = HTMLRenderer().render(fallback)

    _assert_html_presentation_contract(html)
    assert "Deterministic fallback summary." in html
    assert "Synthesis provider" in html
    assert "fallback" in html
    assert "Synthesis model" in html
    assert "Not applicable" in html


def test_html_renderer_renders_appendix_findings_with_source_labels() -> None:
    """Appendix findings retain individual human-readable provenance."""
    report = _enhanced_report(include_enhancements=False).model_copy(
        update={
            "appendix_findings": (
                Finding(
                    title="Appendix finding",
                    description="A lower-ranked supported fact.",
                    supporting_chunk_ids=(_CHUNK_ID,),
                ),
            )
        }
    )

    html = HTMLRenderer().render(report)

    assert "Appendix finding" in html
    assert "A lower-ranked supported fact." in html
    assert "Source 1" in html
    assert str(_CHUNK_ID) not in html


def test_html_renderer_renders_optional_intelligence_through_safe_context() -> None:
    """HTML renders enriched fields, labels, and no internal IDs or scores."""
    report = _enhanced_report().model_copy(
        update={
            "appendix_findings": (
                Finding(
                    title="Appendix source finding",
                    description="A lower-ranked implementation detail.",
                    supporting_chunk_ids=(_SECOND_CHUNK_ID,),
                ),
            ),
            "synthesis_metadata": SynthesisMetadata(
                provider="groq",
                model="test-model",
                elapsed_ms=0.0,
                successful=True,
                source_evidence=(
                    SynthesisSourceEvidence(
                        chunk_id=_CHUNK_ID,
                        confidence=0.9,
                        references=("https://example.com/source",),
                    ),
                    SynthesisSourceEvidence(
                        chunk_id=_SECOND_CHUNK_ID,
                        confidence=0.8,
                        references=("https://example.com/second",),
                    ),
                ),
            ),
            "report_intelligence": ReportIntelligence(
                entity_groups=(
                    EntityGroup(
                        category="Organizations",
                        entities=(
                            NormalizedEntity(
                                name="PaperForge",
                                aliases=("PF",),
                                supporting_chunk_ids=(_CHUNK_ID,),
                                references=("https://example.com/source",),
                                confidence=0.9,
                            ),
                        ),
                    ),
                ),
                definitions=(
                    ConsolidatedDefinition(
                        concept="Evidence",
                        definition="Evidence is supporting information.",
                        related_concepts=("Provenance",),
                        supporting_chunk_ids=(_CHUNK_ID,),
                        references=("https://example.com/source",),
                        confidence=0.84,
                    ),
                ),
                timeline=(
                    IntelligentTimelineEvent(
                        date="2026-07-29",
                        description="The document reports a measured improvement.",
                        supporting_chunk_ids=(_CHUNK_ID,),
                        references=("https://example.com/source",),
                        confidence=0.84,
                    ),
                ),
                findings=(
                    EnrichedFinding(
                        source_kind="finding",
                        source_index=0,
                        title="<strong>Performance improvement</strong>",
                        summary="The document reports a measured improvement.",
                        supporting_chunk_ids=(_CHUNK_ID, _SECOND_CHUNK_ID),
                        references=("https://example.com/source",),
                        confidence=0.92,
                        importance="high",
                    ),
                    EnrichedFinding(
                        source_kind="appendix",
                        source_index=0,
                        title="Implementation context",
                        summary="A lower-ranked implementation detail.",
                        supporting_chunk_ids=(_SECOND_CHUNK_ID,),
                        references=("https://example.com/second",),
                        confidence=0.71,
                        importance="low",
                    ),
                ),
                references=(
                    ConsolidatedReference(
                        reference="https://example.com/consolidated",
                        supporting_chunk_ids=(_CHUNK_ID, _SECOND_CHUNK_ID),
                    ),
                ),
            ),
        }
    )

    first = HTMLRenderer().render(report)
    second = HTMLRenderer().render(report)

    assert first == second
    assert "&lt;strong&gt;Performance improvement&lt;/strong&gt;" in first
    assert "<strong>Performance improvement</strong>" not in first
    assert "HIGH" in first
    assert "LOW" in first
    # Display confidence is calibrated in the shared presentation context;
    # raw immutable model values remain untouched.
    assert "<dt>Confidence</dt><dd>100%</dd>" in first
    assert "<dt>Confidence</dt><dd>60%</dd>" in first
    assert "2 sources" in first
    assert "Organizations" in first
    assert "Also known as: PF" in first
    assert "Related concepts" in first and "Provenance" in first
    assert "https://example.com/consolidated" in first
    assert "Source 1" in first and "Source 2" in first
    assert "score" not in first.lower()
    assert str(_CHUNK_ID) not in first
    assert str(_SECOND_CHUNK_ID) not in first


def test_html_renderer_groups_findings_and_hides_ranked_entity_overflow() -> None:
    """HTML displays primary entities without exposing hidden-mode inventory."""
    ranked_entities = tuple(
        NormalizedEntity(
            name=f"Entity {index:02d}",
            aliases=(),
            supporting_chunk_ids=(_CHUNK_ID,),
            references=("https://example.com/source",),
            confidence=0.9,
        )
        for index in range(1, 11)
    )
    report = _enhanced_report().model_copy(
        update={
            "report_intelligence": ReportIntelligence(
                entity_groups=(
                    EntityGroup(
                        category="Technologies",
                        entities=ranked_entities,
                    ),
                ),
                findings=(
                    EnrichedFinding(
                        source_kind="finding",
                        source_index=0,
                        title="PDF history",
                        summary="PDF was introduced as a portable document format.",
                        supporting_chunk_ids=(_CHUNK_ID,),
                        references=("https://example.com/source",),
                        confidence=0.9,
                        importance="high",
                    ),
                ),
            )
        }
    )

    presentation = ReportComposer().compose(report)
    html = HTMLRenderer().render_presentation(presentation)

    _assert_html_presentation_contract(html)
    overview = next(
        section
        for section in presentation.sections
        if section.anchor_id == "document-overview"
    )
    assert len(overview.entity_groups[0].entities) == 8
    assert len(presentation.hidden_content.entity_groups[0].entities) == 2
    for index in range(1, 9):
        assert f"Entity {index:02d}" in html
    assert "Entity 09" not in html
    assert "Entity 10" not in html
    assert len(report.report_intelligence.entity_groups[0].entities) == 10


def test_html_renderer_renders_visible_metrics_and_statistics_not_hidden_content() -> None:
    """Visible composition tables render without exposing hidden-mode inventory."""
    presentation = ReportComposer().compose(_enhanced_report())
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
    appendix_table = EvidenceTable(
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
                    evidence_tables=(appendix_table,),
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

    html = HTMLRenderer().render_presentation(updated_presentation)

    assert '<figure class="evidence-table evidence-table--key-metrics">' in html
    assert "<figcaption" in html and "Key Metrics</figcaption>" in html
    assert "<th scope=\"col\">Metric</th><th scope=\"col\">Value</th>" in html
    assert "Total pages" in html and "35%" in html
    assert "evidence-table--compression-statistics" in html
    assert "Findings" in html and ">20<" in html
    assert "Supporting Statistics" in html
    assert "evidence-table--appendix-statistics" in html
    assert "Duplicate findings" in html
    assert "Hidden overflow finding" not in html


def test_html_renderer_maps_unexpected_template_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected Jinja failures never escape the report rendering boundary."""
    def fail_template_load(_: str) -> object:
        raise RuntimeError("template failure")

    monkeypatch.setattr(html_renderer, "get_html_template", fail_template_load)

    with pytest.raises(ReportRenderingError, match="Unable to render"):
        HTMLRenderer().render(_enhanced_report())
