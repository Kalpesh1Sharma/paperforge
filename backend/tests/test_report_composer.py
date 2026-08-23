"""Tests for deterministic, immutable research report composition."""

from copy import deepcopy
from datetime import date, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.knowledge import KnowledgeObject
from app.models.parsed_document import ParsedDocument
from app.reports import (
    EnhancedResearchReport,
    Finding,
    HTMLRenderer,
    MarkdownRenderer,
    PresentationEvidence,
    PresentationModel,
    ReportComposer,
    ReportIntelligenceBuilder,
    ResearchReport,
    SynthesisMetadata,
    SynthesisSourceEvidence,
    SynthesizedSection,
    TimelineEvent,
)
from app.reports.exceptions import InvalidResearchReportError
from app.reports.refinement import ReportRefiner
from app.reports.presentation_models import (
    PRESENTATION_SECTION_SPECS,
    PresentationBudget,
    ReportMode,
    TableOfContents,
    TableOfContentsEntry,
)


_CHUNK_IDS = (
    UUID("11111111-1111-4111-8111-111111111111"),
    UUID("22222222-2222-4222-8222-222222222222"),
    UUID("33333333-3333-4333-8333-333333333333"),
    UUID("44444444-4444-4444-8444-444444444444"),
    UUID("55555555-5555-4555-8555-555555555555"),
    UUID("66666666-6666-4666-8666-666666666666"),
    UUID("77777777-7777-4777-8777-777777777777"),
    UUID("88888888-8888-4888-8888-888888888888"),
    UUID("99999999-9999-4999-8999-999999999999"),
    UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
)


def _report() -> EnhancedResearchReport:
    """Build a report large enough to exercise deterministic routing rules."""
    findings = tuple(
        Finding(
            title=f"Finding {index + 1}",
            description=(
                f"The document records architecture result {index + 1} "
                "with traceable evidence."
            ),
            supporting_chunk_ids=(chunk_id,),
        )
        for index, chunk_id in enumerate(_CHUNK_IDS[:9])
    )
    definitions = tuple(
        f"Concept {index + 1}: Definition {index + 1}."
        for index in range(7)
    )
    evidence = tuple(
        SynthesisSourceEvidence(
            chunk_id=chunk_id,
            confidence=0.5 + (index / 100.0),
            references=(f"https://example.com/source-{index + 1}",),
        )
        for index, chunk_id in enumerate(_CHUNK_IDS)
    )
    return EnhancedResearchReport(
        base_report=ResearchReport(
            title="Canonical Research Report",
            executive_summary="The canonical report retains deterministic facts.",
            important_entities=("PaperForge", "PDF"),
            important_definitions=definitions,
            important_metrics=("95%",),
            references=("https://example.com/base",),
        ),
        executive_summary=(
            "The report presents source-backed research findings.\n\n"
            "It distinguishes primary insights from supporting material."
        ),
        findings=findings,
        appendix_findings=(
            Finding(
                title="Appendix finding",
                description="The appendix retains a secondary source-backed fact.",
                supporting_chunk_ids=(_CHUNK_IDS[9],),
            ),
        ),
        sections=(
            SynthesizedSection(
                heading="Supported analysis",
                content="A supported section retains its original provenance.",
                supporting_chunk_ids=(_CHUNK_IDS[0],),
            ),
        ),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            source_evidence=evidence,
        ),
    )


def _source_document() -> ParsedDocument:
    """Return source metadata with correctly matched parser counts."""
    text = "PaperForge composes deterministic research reports."
    return ParsedDocument(
        filename="paper.pdf",
        file_type="pdf",
        extracted_text=text,
        page_count=12,
        word_count=5,
        character_count=len(text),
        metadata={"title": "Source Metadata Title"},
    )


def _section(model: PresentationModel, key: str):
    """Return one composed section by its known public key."""
    return next(section for section in model.sections if section.key == key)


def _optional_section(model: PresentationModel, key: str):
    """Return a section only when it has substantive reader-facing content."""
    return next((section for section in model.sections if section.key == key), None)


def _finding_cards(section) -> tuple:
    """Flatten display-only finding groups for concise routing assertions."""
    return tuple(card for group in section.finding_groups for card in group.findings)


def test_composer_returns_immutable_deterministic_model_without_mutation() -> None:
    """Composition is reproducible and leaves canonical source objects untouched."""
    report = _report()
    source_document = _source_document()
    report_before = deepcopy(report.model_dump(mode="python"))
    source_before = deepcopy(source_document.model_dump(mode="python"))

    first = ReportComposer().compose(report, source_document, date(2025, 1, 2))
    second = ReportComposer().compose(report, source_document, date(2025, 1, 2))

    assert first == second
    assert first.cover.title == "Source Metadata Title"
    assert first.cover.filename == "paper.pdf"
    assert first.cover.file_type == "PDF"
    assert first.cover.page_count == 12
    assert first.cover.generated_on == date(2025, 1, 2)
    assert first.cover.status == "AI-enhanced"
    assert first.cover.knowledge_object_count == len(_CHUNK_IDS)
    assert report.model_dump(mode="python") == report_before
    assert source_document.model_dump(mode="python") == source_before

    with pytest.raises(ValidationError):
        first.cover.title = "Mutated"  # type: ignore[misc]


def test_composer_projects_an_ordered_section_subset_into_toc() -> None:
    """TOC entries are an immutable exact projection of actual sections."""
    model = ReportComposer().compose(_report())

    known_keys = tuple(key for key, _, _ in PRESENTATION_SECTION_SPECS)
    actual_keys = tuple(section.key for section in model.sections)
    assert actual_keys == tuple(key for key in known_keys if key in actual_keys)
    assert actual_keys
    assert "research-methodology" not in actual_keys
    assert "historical-timeline" not in actual_keys
    assert "important-concepts" not in actual_keys
    assert "appendix" in actual_keys
    assert tuple(
        (entry.heading, entry.anchor_id) for entry in model.table_of_contents.entries
    ) == tuple((section.heading, section.anchor_id) for section in model.sections)
    assert len({entry.anchor_id for entry in model.table_of_contents.entries}) == len(
        model.sections
    )

    invalid_payload = model.model_dump(mode="python")
    invalid_payload["table_of_contents"] = {"entries": ()}
    with pytest.raises(ValidationError):
        PresentationModel.model_validate(invalid_payload)


def test_composer_routes_key_insights_concepts_and_secondary_content() -> None:
    """Selected content is bounded while every remaining item reaches its appendix."""
    model = ReportComposer().compose(_report())
    key_insights = _finding_cards(_section(model, "key-insights"))
    technical = _finding_cards(_section(model, "technical-analysis"))
    concepts_section = _optional_section(model, "important-concepts")
    appendix = _section(model, "appendix")

    assert len(key_insights) == 8
    assert any(card.key == "finding-1" for card in technical)
    assert any(card.key == "supported-section-1" for card in technical)
    # Label-only values such as ``Concept 1: Definition 1`` remain supporting
    # material rather than becoming a primary explanatory concept card.
    assert concepts_section is None
    appendix_findings = tuple(
        card
        for group in appendix.appendix_groups
        for card in group.findings
    )
    appendix_concepts = tuple(
        card
        for group in appendix.appendix_groups
        for card in group.concepts
    )
    assert tuple(card.key for card in appendix_findings) == ("appendix-finding-1",)
    assert tuple(card.key for card in appendix_concepts) == tuple(
        f"concept-{index}" for index in range(1, 8)
    )
    assert all(
        card.evidence.supporting_chunk_ids
        and card.evidence.source_labels
        for card in key_insights
    )


def test_composer_caps_abstract_and_removes_duplicate_summary_paragraphs() -> None:
    """The extractive abstract remains bounded without padded duplicate content."""
    long_summary = " ".join(f"word{index}" for index in range(230)) + "."
    report = _report().model_copy(update={"executive_summary": long_summary})

    model = ReportComposer().compose(report)
    abstract = _section(model, "abstract").intro
    executive_summary = _section(model, "executive-summary").intro

    assert len(abstract) == 1
    assert len(abstract[0].split()) <= 180
    assert executive_summary == (long_summary,)


def test_composer_preserves_intelligence_source_provenance() -> None:
    """Intelligence cards retain raw IDs internally and labels for renderers."""
    chunk_id = _CHUNK_IDS[0]
    knowledge_objects = (
        KnowledgeObject(
            chunk_id=chunk_id,
            entities=("PDF",),
            facts=("PDF was standardized in 2008.",),
            definitions=("PDF: A portable document format.",),
            metrics=(),
            dates=("2008",),
            references=("https://example.com/pdf",),
            confidence=0.9,
        ),
    )
    report = EnhancedResearchReport(
        base_report=ResearchReport(
            title="PDF Report",
            executive_summary="Canonical PDF report.",
        ),
        executive_summary="The source covers a PDF standard.",
        findings=(
            Finding(
                title="PDF standard",
                description="PDF was standardized in 2008.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=chunk_id,
                    confidence=0.9,
                    references=("https://example.com/pdf",),
                ),
            ),
        ),
    )
    enriched = ReportIntelligenceBuilder().build(report, knowledge_objects)

    model = ReportComposer().compose(enriched)
    insight = _finding_cards(_section(model, "key-insights"))[0]

    assert model.hidden_content.entity_groups[0].entities[0].evidence.supporting_chunk_ids == (
        chunk_id,
    )
    assert model.hidden_content.entity_groups[0].entities[0].evidence.source_labels == (
        "Source 1",
    )
    assert insight.evidence.supporting_chunk_ids == (chunk_id,)


def test_composer_rejects_malformed_inputs_and_evidence_invariants() -> None:
    """Invalid caller objects cannot silently produce a partial presentation."""
    report = _report()
    invalid_document = ParsedDocument.model_construct(
        filename="invalid.pdf",
        file_type="pdf",
        extracted_text="one two",
        page_count=1,
        word_count=2,
        character_count=999,
        metadata={},
    )

    with pytest.raises(InvalidResearchReportError):
        ReportComposer().compose(object())  # type: ignore[arg-type]
    with pytest.raises(InvalidResearchReportError):
        ReportComposer().compose(report, invalid_document)
    with pytest.raises(InvalidResearchReportError):
        ReportComposer().compose(report, generated_on=datetime(2025, 1, 2))
    with pytest.raises(ValidationError):
        PresentationEvidence(
            supporting_chunk_ids=(_CHUNK_IDS[0],),
            source_labels=(),
            source_count=1,
        )


def test_professional_composition_curates_generic_titles_contact_details_and_dates() -> None:
    """Publication mode suppresses low-value prose while retaining source-backed data."""
    contact_finding = Finding(
        title="Contact email",
        description="Email: analyst@example.com.",
        supporting_chunk_ids=(_CHUNK_IDS[0],),
    )
    event_finding = Finding(
        title="Internship completed",
        description="The internship was completed in 2025.",
        supporting_chunk_ids=(_CHUNK_IDS[1],),
    )
    base_report = ResearchReport(
        title="Research Report",
        executive_summary="Canonical summary.",
        timeline=(
            TimelineEvent(
                date="2022",
                description="Extracted date: 2022.",
                supporting_chunk_ids=(_CHUNK_IDS[0],),
            ),
            TimelineEvent(
                date="2025",
                description="The internship was completed in 2025.",
                supporting_chunk_ids=(_CHUNK_IDS[1],),
            ),
        ),
    )
    report = _report().model_copy(
        update={
            "base_report": base_report,
            "executive_summary": (
                "Email: analyst@example.com. "
                "The internship was completed in 2025."
            ),
            "findings": (contact_finding, event_finding),
            "appendix_findings": (),
            "sections": (),
        }
    )
    source = _source_document().model_copy(
        update={"filename": "input.pdf", "metadata": {}}
    )

    model = ReportComposer().compose(report, source)
    published_text = " ".join(
        paragraph
        for section in model.sections
        for paragraph in section.intro
    )
    visible_findings = tuple(
        card
        for section in model.sections
        for group in section.finding_groups
        for card in group.findings
    )
    timeline = _section(model, "historical-timeline").timeline

    assert model.cover.title == "Research Report"
    assert "analyst@example.com" not in published_text
    assert all("Contact email" != card.title for card in visible_findings)
    assert any(card.title == "Contact email" for card in model.hidden_content.findings)
    assert tuple(card.date for card in timeline) == ("2025",)
    assert timeline[0].description == "The internship was completed in 2025."
    assert visible_findings[0].evidence.source_labels == ("input.pdf · excerpt 2",)
    assert len(visible_findings[0].evidence.source_labels) == len(
        visible_findings[0].evidence.supporting_chunk_ids
    )


def test_presentation_model_validates_an_ordered_subset_of_known_sections() -> None:
    """Sections may be omitted, but known ordering and navigation remain strict."""
    model = ReportComposer().compose(_report())
    first = model.sections[0]
    subset = model.model_copy(
        update={
            "sections": (first,),
            "table_of_contents": TableOfContents(
                entries=(
                    TableOfContentsEntry(
                        heading=first.heading,
                        anchor_id=first.anchor_id,
                    ),
                )
            ),
        }
    )
    assert PresentationModel.model_validate(subset.model_dump(mode="python")) == subset

    payload = model.model_dump(mode="python")
    payload["sections"] = (payload["sections"][0], payload["sections"][0])
    with pytest.raises(ValidationError):
        PresentationModel.model_validate(payload)


def test_professional_curation_hides_header_blobs_and_preserves_long_technical_prose() -> None:
    """Header residue is hidden while substantive detailed evidence remains visible."""
    header = Finding(
        title="KALPESH SHARMA Jaipur Rajasthan",
        description=(
            "KALPESH SHARMA Jaipur Rajasthan +91 9876543210 "
            "kalpesh2199@example.com Portfolio LinkedIn GitHub PROFESSIONAL SUMMARY."
        ),
        supporting_chunk_ids=(_CHUNK_IDS[0],),
    )
    multi_section = Finding(
        title="Resume content",
        description=(
            "EDUCATION B.Tech coursework SKILLS & TECHNOLOGIES Python SQL "
            "EXPERIENCE Data Engineer PROJECTS Retrieval system CERTIFICATIONS "
            "Cloud credential REFERENCES available on request."
        ),
        supporting_chunk_ids=(_CHUNK_IDS[1],),
    )
    technical = Finding(
        title="Production retrieval pipeline",
        description=(
            "The production retrieval pipeline uses deterministic chunk selection, "
            "FAISS cosine similarity, source-backed citations, and two-layer "
            "hallucination guardrails to keep generated answers grounded in evidence."
        ),
        supporting_chunk_ids=(_CHUNK_IDS[2],),
    )
    appendix_header = Finding(
        title="Profile links",
        description="Portfolio LinkedIn GitHub kalpesh2199@example.com.",
        supporting_chunk_ids=(_CHUNK_IDS[3],),
    )
    base_report = ResearchReport(
        title="Research Report",
        executive_summary="Canonical summary.",
        timeline=(
            TimelineEvent(
                date="2199",
                description="Extracted date: 2199.",
                supporting_chunk_ids=(_CHUNK_IDS[0],),
            ),
        ),
    )
    report = _report().model_copy(
        update={
            "base_report": base_report,
            "executive_summary": (
                "KALPESH SHARMA Jaipur Rajasthan +91 9876543210 "
                "kalpesh2199@example.com Portfolio LinkedIn GitHub PROFESSIONAL SUMMARY. "
                "The document focuses on KALPESH, SHARMA, PROFESSIONAL, and SUMMARY. "
                "The extracted chronology includes 2199, 2022, and 2026. "
                "The source documents a production retrieval pipeline with guardrails."
            ),
            "findings": (header, multi_section, technical),
            "appendix_findings": (appendix_header,),
            "sections": (),
        }
    )

    model = ReportComposer().compose(report)
    publication_text = "\n".join(
        value
        for section in model.sections
        for value in section.intro
    )
    visible_findings = tuple(
        card
        for section in model.sections
        for group in section.finding_groups
        for card in group.findings
    )
    hidden_titles = tuple(card.title for card in model.hidden_content.findings)

    assert "kalpesh2199@example.com" not in publication_text
    assert "The document focuses on" not in publication_text
    assert "extracted chronology includes" not in publication_text.casefold()
    assert tuple(card.title for card in visible_findings) == (
        "Production retrieval pipeline",
    )
    assert {header.title, multi_section.title, appendix_header.title}.issubset(hidden_titles)
    assert all(section.key != "historical-timeline" for section in model.sections)


def test_prefix_title_uses_only_the_nonredundant_summary_in_renderers() -> None:
    """A title repeated at the start of a body is not rendered as a second heading."""
    chunk_id = _CHUNK_IDS[0]
    title = "Built a production RAG pipeline with two-layer hallucination guardrails"
    summary = (
        "Built a production RAG pipeline with two-layer hallucination guardrails "
        "using FAISS cosine similarity and source-backed retrieval."
    )
    finding = Finding(
        title=title,
        description=summary,
        supporting_chunk_ids=(chunk_id,),
    )
    report = EnhancedResearchReport(
        base_report=ResearchReport(
            title="Research Report",
            executive_summary="Canonical summary.",
        ),
        executive_summary="The source describes a production retrieval implementation.",
        findings=(finding,),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        ),
    )

    model = ReportComposer().compose(report)
    insight = next(
        card
        for section in model.sections
        for group in section.finding_groups
        for card in group.findings
    )
    markdown = MarkdownRenderer().render_presentation(model)
    html = HTMLRenderer().render_presentation(model)

    assert insight.summary_includes_title is True
    assert f"#### {title}" not in markdown
    assert summary in markdown
    assert f">{title}</h4>" not in html
    assert summary in html

    payload = model.model_dump(mode="python")
    payload["sections"] = tuple(reversed(payload["sections"]))
    with pytest.raises(ValidationError):
        PresentationModel.model_validate(payload)
    payload = model.model_dump(mode="python")
    payload["sections"] = (
        {**payload["sections"][0], "heading": "Incorrect heading"},
        *payload["sections"][1:],
    )
    with pytest.raises(ValidationError):
        PresentationModel.model_validate(payload)


def test_publication_curation_hides_navigation_chrome_from_abstract_findings_and_evidence() -> None:
    """A leading multi-label web header remains hidden rather than becoming evidence."""
    chrome = Finding(
        title="Home Search Categories Archive Tags",
        description=(
            "Home Search Categories Archive Tags Home » Fileformat.Blogs. "
            "Products Support Websites About."
        ),
        supporting_chunk_ids=(_CHUNK_IDS[0],),
    )
    substantive = Finding(
        title="MCPACK files package Minecraft assets",
        description=(
            "MCPACK files package Minecraft assets for portable distribution."
        ),
        supporting_chunk_ids=(_CHUNK_IDS[1],),
    )
    ordinary_prose = Finding(
        title="Players can manage content at home",
        description=(
            "Players can manage content at home without changing package compatibility."
        ),
        supporting_chunk_ids=(_CHUNK_IDS[2],),
    )
    report = _report().model_copy(
        update={
            "executive_summary": (
                "Home Search Categories Archive Tags Home » Fileformat.Blogs. "
                "MCPACK files package Minecraft assets for portable distribution."
            ),
            "findings": (chrome, substantive, ordinary_prose),
            "appendix_findings": (),
            "sections": (),
            "synthesis_metadata": SynthesisMetadata(
                provider="groq",
                model="test-model",
                elapsed_ms=0.0,
                successful=True,
                source_evidence=(
                    SynthesisSourceEvidence(chunk_id=_CHUNK_IDS[0], confidence=0.99),
                    SynthesisSourceEvidence(chunk_id=_CHUNK_IDS[1], confidence=0.70),
                    SynthesisSourceEvidence(chunk_id=_CHUNK_IDS[2], confidence=0.60),
                ),
            ),
        }
    )

    model = ReportComposer().compose(report)
    abstract = _section(model, "abstract").intro[0]
    visible_cards = tuple(
        card
        for section in model.sections
        for group in section.finding_groups
        for card in group.findings
    )
    quality_rows = dict(_section(model, "evidence-summary").evidence_tables[0].rows)

    assert "Home Search Categories" not in abstract
    assert chrome.title not in tuple(card.title for card in visible_cards)
    assert chrome.title in tuple(card.title for card in model.hidden_content.findings)
    assert ordinary_prose.title in tuple(card.title for card in visible_cards)
    assert quality_rows["Highest-confidence finding"] != chrome.title
    assert quality_rows["Most-supported finding"] != chrome.title


def test_cover_uses_only_a_trustworthy_leading_extracted_heading() -> None:
    """A concise leading document heading is the final deterministic title fallback."""
    heading_text = "Minecraft and MCPACK Files\n\nMCPACK files package Minecraft content for distribution."
    source = ParsedDocument(
        filename="minecraft.pdf",
        file_type="pdf",
        extracted_text=heading_text,
        page_count=2,
        word_count=len(heading_text.split()),
        character_count=len(heading_text),
        metadata={},
    )
    generic_text = "Home\n\nThe document describes substantive package behavior in detail."
    generic_source = ParsedDocument(
        filename="home.pdf",
        file_type="pdf",
        extracted_text=generic_text,
        page_count=1,
        word_count=len(generic_text.split()),
        character_count=len(generic_text),
        metadata={},
    )
    report = _report().model_copy(
        update={"base_report": _report().base_report.model_copy(update={"title": "Report"})}
    )

    assert ReportComposer().compose(report, source).cover.title == "Minecraft and MCPACK Files"
    assert ReportComposer().compose(report, generic_source).cover.title == "Research Report"


def test_cover_recovers_heading_after_a_separable_navigation_breadcrumb() -> None:
    """A concise title may follow web chrome when article metadata clearly follows it."""
    text = (
        "Home Search Categories Archive Tags Home » Fileformat.Blogs » "
        "Minecraft and MCPACK Files June 10, 2025 7 min read\n\n"
        "MCPACK files package Minecraft content for portable distribution."
    )
    source = ParsedDocument(
        filename="article.pdf",
        file_type="pdf",
        extracted_text=text,
        page_count=2,
        word_count=len(text.split()),
        character_count=len(text),
        metadata={},
    )
    report = _report().model_copy(
        update={"base_report": _report().base_report.model_copy(update={"title": "Report"})}
    )

    assert ReportComposer().compose(report, source).cover.title == "Minecraft and MCPACK Files"


def test_cover_recovers_title_from_realistic_breadcrumb_metadata_shape() -> None:
    """Navigation, article metadata, and body prose never become the extracted title."""
    text = (
        "Home Search Categories Archive Tags Home » Fileformat.Blogs\n"
        "Minecraft and MCPACK Files\n"
        "February 27, 2025 · 7 min · Shakeel Faiz\n"
        "Last Updated: 27 Feb, 2025\n"
        "What is Minecraft?\n"
        "Products Support Websites About\n"
        "Minecraft is a globally recognized sandbox game with an open-ended world."
    )
    source = ParsedDocument(
        filename="article.pdf",
        file_type="pdf",
        extracted_text=text,
        page_count=2,
        word_count=len(text.split()),
        character_count=len(text),
        metadata={},
    )
    report = _report().model_copy(
        update={"base_report": _report().base_report.model_copy(update={"title": "Report"})}
    )

    assert ReportComposer().compose(report, source).cover.title == "Minecraft and MCPACK Files"


def test_timeline_keeps_release_events_but_not_bare_dates() -> None:
    """Event-bearing milestones survive the date-artifact curation rule."""
    report = _report().model_copy(
        update={
            "base_report": _report().base_report.model_copy(
                update={
                    "timeline": (
                        TimelineEvent(
                            date="2009",
                            description="Minecraft alpha release.",
                            supporting_chunk_ids=(_CHUNK_IDS[0],),
                        ),
                        TimelineEvent(
                            date="2011",
                            description="Minecraft full launch.",
                            supporting_chunk_ids=(_CHUNK_IDS[1],),
                        ),
                        TimelineEvent(
                            date="2010",
                            description="Document records the date 2010.",
                            supporting_chunk_ids=(_CHUNK_IDS[2],),
                        ),
                    )
                }
            )
        }
    )

    timeline = _section(ReportComposer().compose(report), "historical-timeline").timeline

    assert tuple((card.date, card.description) for card in timeline) == (
        ("2009", "Minecraft alpha release."),
        ("2011", "Minecraft full launch."),
    )


def test_professional_mode_hides_page_count_only_metrics() -> None:
    """Page metadata remains on the cover instead of becoming research evidence."""
    model = ReportComposer().compose(_report(), _source_document())
    evidence = _section(model, "evidence-summary")

    assert all(table.title != "Key Metrics" for table in evidence.evidence_tables)
    assert model.cover.page_count == 12


def test_isolated_general_technical_card_has_no_publication_subheading() -> None:
    """Professional rendering avoids a generic heading without changing technical mode."""
    finding = Finding(
        title="Release notes",
        description="The source outlines compatibility outcomes and user behavior.",
        supporting_chunk_ids=(_CHUNK_IDS[0],),
    )
    report = _report().model_copy(
        update={"findings": (finding,), "appendix_findings": (), "sections": ()}
    )
    budget = PresentationBudget(key_insights_limit=0, technical_analysis_limit=1)

    professional = ReportComposer(budget=budget).compose(report)
    technical = ReportComposer(mode=ReportMode.TECHNICAL, budget=budget).compose(report)

    assert "### General" not in MarkdownRenderer().render_presentation(professional)
    assert "### General" in MarkdownRenderer().render_presentation(technical)


def test_refined_heading_body_cleanup_reaches_all_professional_finding_views() -> None:
    """A repeated structural heading is absent from abstract and visible finding prose."""
    chunk_id = _CHUNK_IDS[0]
    base_report = ResearchReport(
        title="Report",
        executive_summary="Canonical summary.",
        findings=(
            Finding(
                title="The Open-Ended Nature of Minecraft",
                description=(
                    "The Open-Ended Nature of Minecraft Minecraft is unique in "
                    "that it lacks mandatory objectives."
                ),
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
    )
    knowledge = KnowledgeObject(
        chunk_id=chunk_id,
        entities=(),
        facts=(),
        definitions=(),
        metrics=(),
        dates=(),
        references=(),
        confidence=0.9,
    )
    plan = ReportRefiner.build_plan(base_report, (knowledge,))
    report = EnhancedResearchReport(
        base_report=base_report,
        executive_summary=plan.executive_summary,
        findings=plan.findings,
        appendix_findings=plan.appendix_findings,
        synthesis_metadata=SynthesisMetadata(
            provider="fallback",
            model=None,
            elapsed_ms=0.0,
            successful=True,
            enhanced=False,
            fallback=True,
            reason="provider_unavailable",
            source_evidence=plan.source_evidence,
        ),
    )

    model = ReportComposer().compose(report)
    abstract = _section(model, "abstract").intro[0]
    visible_prose = " ".join(
        (paragraph for section in model.sections for paragraph in section.intro)
    ) + " " + " ".join(
        card.summary
        for section in model.sections
        for group in section.finding_groups
        for card in group.findings
    )

    assert "The Open-Ended Nature of Minecraft Minecraft" not in visible_prose
    assert "The Open-Ended Nature of Minecraft Minecraft" not in abstract
    assert "Minecraft is unique in that it lacks mandatory objectives." in abstract
