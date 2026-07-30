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
    PresentationEvidence,
    PresentationModel,
    ReportComposer,
    ReportIntelligenceBuilder,
    ResearchReport,
    SynthesisMetadata,
    SynthesisSourceEvidence,
    SynthesizedSection,
)
from app.reports.exceptions import InvalidResearchReportError


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
    """Return one known composed section by its fixed public key."""
    return next(section for section in model.sections if section.key == key)


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


def test_composer_projects_the_exact_fixed_section_order_into_toc() -> None:
    """TOC entries are an immutable exact projection of ordered report sections."""
    model = ReportComposer().compose(_report())

    assert tuple(section.key for section in model.sections) == (
        "abstract",
        "document-overview",
        "research-methodology",
        "executive-summary",
        "key-insights",
        "technical-analysis",
        "historical-timeline",
        "important-concepts",
        "evidence-summary",
        "appendix",
    )
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
    concepts = _section(model, "important-concepts").concepts
    appendix = _section(model, "appendix")

    assert len(key_insights) == 8
    assert any(card.key == "finding-1" for card in technical)
    assert any(card.key == "supported-section-1" for card in technical)
    assert len(concepts) == 6
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
    assert tuple(card.key for card in appendix_concepts) == ("concept-7",)
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
    assert len(abstract[0].split()) == 180
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
    overview = _section(model, "document-overview")
    concepts = _section(model, "important-concepts")
    insight = _finding_cards(_section(model, "key-insights"))[0]

    assert overview.entity_groups[0].entities[0].evidence.supporting_chunk_ids == (
        chunk_id,
    )
    assert overview.entity_groups[0].entities[0].evidence.source_labels == (
        "Source 1",
    )
    assert concepts.concepts[0].evidence.supporting_chunk_ids == (chunk_id,)
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
