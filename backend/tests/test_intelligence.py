"""Tests for deterministic, presentation-only report intelligence."""

from collections import Counter
from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.knowledge import KnowledgeObject
from app.reports import (
    ConsolidatedDefinition,
    ConsolidatedReference,
    EnhancedResearchReport,
    Finding,
    NormalizedEntity,
    ReportIntelligence,
    ReportIntelligenceBuilder,
    ReportSynthesisError,
    ResearchReport,
    SynthesisMetadata,
    TimelineEvent,
)


_CHUNK_IDS = (
    UUID("11111111-1111-4111-8111-111111111111"),
    UUID("22222222-2222-4222-8222-222222222222"),
    UUID("33333333-3333-4333-8333-333333333333"),
    UUID("44444444-4444-4444-8444-444444444444"),
    UUID("55555555-5555-4555-8555-555555555555"),
)


def _knowledge_objects() -> tuple[KnowledgeObject, ...]:
    """Return source-backed data spanning each intelligence concern."""
    first, second, third, fourth, orphan = _CHUNK_IDS
    return (
        KnowledgeObject(
            chunk_id=first,
            entities=(
                "PDF Documents",
                "Adobe Acrobat",
                "PyPDF",
                "ISO 32000",
                "Python",
                "DOCX",
                "Digital Signature",
                "Unfamiliar System",
            ),
            facts=(
                "Adobe introduced PDF in 1993 for platform-independent document rendering.",
            ),
            definitions=(
                "PDF: A portable document format used for reliable document exchange.",
                "OCR refers to optical character recognition.",
                "An unstructured definition statement.",
            ),
            metrics=("95%",),
            dates=("1993", "January"),
            references=(" Zeta Reference ", "Alpha Reference"),
            confidence=0.9,
        ),
        KnowledgeObject(
            chunk_id=second,
            entities=("PDF", "Adobe Reader", "PDF Parsers", "Apache PDFBox"),
            facts=("ISO 32000 was standardized in 2008.",),
            definitions=(
                "PDF is a portable document format that preserves document layout across platforms.",
                "OCR refers to optical character recognition.",
            ),
            metrics=(),
            dates=("2008", "March 2008"),
            references=("Alpha  Reference",),
            confidence=0.8,
        ),
        KnowledgeObject(
            chunk_id=third,
            entities=("ISO 32000",),
            facts=("ISO 32000 was standardized in 2008.",),
            definitions=("PDF means a portable document format.",),
            metrics=(),
            dates=("2008",),
            references=("Beta Reference",),
            confidence=0.7,
        ),
        KnowledgeObject(
            chunk_id=fourth,
            entities=("PDF",),
            facts=("The project released version 2.0 on 2024-05-10.",),
            definitions=(),
            metrics=(),
            dates=("2024-05-10", "2020"),
            references=("Gamma Reference",),
            confidence=1.0,
        ),
        KnowledgeObject(
            chunk_id=orphan,
            entities=(),
            facts=("The team met in 2020.",),
            definitions=(),
            metrics=(),
            dates=("2020",),
            references=("Orphan Reference",),
            confidence=0.2,
        ),
    )


def _enhanced_report() -> EnhancedResearchReport:
    """Return a valid immutable overlay with canonical claims unchanged."""
    first, second, third, fourth, _ = _CHUNK_IDS
    repeated_description = (
        "Adobe introduced PDF in 1993 for platform-independent document rendering."
    )
    base_report = ResearchReport(
        title="PDF Research Report",
        executive_summary="Canonical PDF research summary.",
        findings=(
            Finding(
                title="Canonical finding",
                description=repeated_description,
                supporting_chunk_ids=(first,),
            ),
        ),
        important_entities=("PDF",),
        important_definitions=("PDF is a document format.",),
        important_metrics=("95%",),
        timeline=(
            TimelineEvent(
                date="1993",
                description=repeated_description,
                supporting_chunk_ids=(first,),
            ),
        ),
        references=("Alpha Reference",),
        sections=(),
    )
    return EnhancedResearchReport(
        base_report=base_report,
        executive_summary=(
            "PDF research covers Adobe's document-format work.\n\n"
            "The supplied evidence records standards and releases."
        ),
        findings=(
            Finding(
                title=repeated_description,
                description=repeated_description,
                supporting_chunk_ids=(first,),
            ),
            Finding(
                title="ISO standardization",
                description="ISO 32000 was standardized in 2008.",
                supporting_chunk_ids=(second, third),
            ),
        ),
        appendix_findings=(
            Finding(
                title="Release event",
                description="The project released version 2.0 on 2024-05-10.",
                supporting_chunk_ids=(fourth,),
            ),
        ),
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        ),
    )


def _entity_map(report: EnhancedResearchReport) -> dict[str, object]:
    """Index generated entity groups by their public category labels."""
    assert report.report_intelligence is not None
    return {
        group.category: group.entities
        for group in report.report_intelligence.entity_groups
    }


def _empty_enhanced_report() -> EnhancedResearchReport:
    """Build a report shell for focused definition-intelligence tests."""
    return EnhancedResearchReport(
        base_report=ResearchReport(
            title="Definition Report",
            executive_summary="Canonical definition report.",
        ),
        executive_summary="Definition intelligence is being validated.",
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        ),
    )


def test_builder_creates_an_immutable_overlay_without_changing_canonical_data() -> None:
    """Intelligence is additive and preserves canonical object identity exactly."""
    report = _enhanced_report()
    knowledge_objects = _knowledge_objects()
    before_report = deepcopy(report.model_dump(mode="python"))
    before_knowledge = tuple(
        deepcopy(knowledge_object.model_dump(mode="python"))
        for knowledge_object in knowledge_objects
    )

    result = ReportIntelligenceBuilder().build(report, knowledge_objects)

    assert result is not report
    assert result.base_report is report.base_report
    assert result.executive_summary is report.executive_summary
    assert result.findings is report.findings
    assert result.appendix_findings is report.appendix_findings
    assert result.sections is report.sections
    assert result.synthesis_metadata is report.synthesis_metadata
    assert report.report_intelligence is None
    assert result.report_intelligence is not None
    assert report.model_dump(mode="python") == before_report
    assert tuple(
        knowledge_object.model_dump(mode="python")
        for knowledge_object in knowledge_objects
    ) == before_knowledge

    with pytest.raises(ValidationError):
        result.report_intelligence = None  # type: ignore[misc]


def test_builder_normalizes_entities_in_fixed_category_and_alpha_order() -> None:
    """Curated aliases merge while unknown values remain separate and traceable."""
    result = ReportIntelligenceBuilder().build(_enhanced_report(), _knowledge_objects())
    groups = _entity_map(result)

    assert tuple(groups) == (
        "Organizations",
        "Technologies",
        "Standards",
        "Libraries",
        "Programming Languages",
        "File Formats",
        "Concepts",
        "Other",
    )
    organizations = groups["Organizations"]
    technologies = groups["Technologies"]
    libraries = groups["Libraries"]
    assert tuple(entity.name for entity in organizations) == ("Adobe",)
    assert organizations[0].aliases == ("Adobe Acrobat", "Adobe Reader")
    assert tuple(entity.name for entity in technologies) == ("PDF",)
    assert technologies[0].aliases == ("PDF Documents", "PDF", "PDF Parsers")
    assert tuple(entity.name for entity in libraries) == ("Apache PDFBox", "PyPDF")
    assert groups["Other"][0].name == "Unfamiliar System"
    assert technologies[0].supporting_chunk_ids == (
        _CHUNK_IDS[0],
        _CHUNK_IDS[1],
        _CHUNK_IDS[3],
    )
    assert technologies[0].confidence == pytest.approx(0.9)


def test_builder_consolidates_definitions_and_retains_related_evidence() -> None:
    """Equivalent concepts keep the best wording and source-backed relations."""
    result = ReportIntelligenceBuilder().build(_enhanced_report(), _knowledge_objects())
    assert result.report_intelligence is not None
    definitions = {
        definition.concept: definition
        for definition in result.report_intelligence.definitions
    }

    pdf = definitions["PDF"]
    assert pdf.definition == (
        "a portable document format that preserves document layout across "
        "platforms."
    )
    assert pdf.supporting_chunk_ids == (_CHUNK_IDS[0], _CHUNK_IDS[1], _CHUNK_IDS[2])
    assert pdf.related_concepts == ("OCR",)
    assert pdf.references == ("Zeta Reference", "Alpha Reference", "Beta Reference")
    assert any(
        definition.definition == "An unstructured definition statement."
        for definition in definitions.values()
    )


def test_builder_groups_pdf_alias_definition_concepts_before_validation() -> None:
    """PDF aliases emit one canonical definition with all source evidence."""
    first, second, third = _CHUNK_IDS[:3]
    knowledge_objects = (
        KnowledgeObject(
            chunk_id=first,
            entities=(),
            facts=(),
            definitions=("PDF: A short complete definition.",),
            metrics=(),
            dates=(),
            references=("First citation",),
            confidence=0.4,
        ),
        KnowledgeObject(
            chunk_id=second,
            entities=(),
            facts=(),
            definitions=(
                "Portable Document Format: A longer complete definition with "
                "more useful source-backed detail.",
            ),
            metrics=(),
            dates=(),
            references=("Second citation", "Shared citation"),
            confidence=0.8,
        ),
        KnowledgeObject(
            chunk_id=third,
            entities=(),
            facts=(),
            definitions=("PDF means a concise duplicate definition.",),
            metrics=(),
            dates=(),
            references=("Shared citation", "Third citation"),
            confidence=0.6,
        ),
    )

    result = ReportIntelligenceBuilder().build(
        _empty_enhanced_report(),
        knowledge_objects,
    )

    assert result.report_intelligence is not None
    definitions = result.report_intelligence.definitions
    assert len(definitions) == 1
    definition = definitions[0]
    assert definition.concept == "PDF"
    assert definition.definition == (
        "A longer complete definition with more useful source-backed detail."
    )
    assert definition.supporting_chunk_ids == (first, second, third)
    assert definition.references == (
        "First citation",
        "Second citation",
        "Shared citation",
        "Third citation",
    )
    assert definition.confidence == pytest.approx(0.6)


def test_builder_keeps_opaque_definitions_in_a_reserved_concept_namespace() -> None:
    """An unparseable value cannot collide with a parsed canonical concept."""
    first, second = _CHUNK_IDS[:2]
    result = ReportIntelligenceBuilder().build(
        _empty_enhanced_report(),
        (
            KnowledgeObject(
                chunk_id=first,
                entities=(),
                facts=(),
                definitions=("PDF",),
                metrics=(),
                dates=(),
                references=(),
                confidence=0.5,
            ),
            KnowledgeObject(
                chunk_id=second,
                entities=(),
                facts=(),
                definitions=("PDF: A portable document format.",),
                metrics=(),
                dates=(),
                references=(),
                confidence=0.8,
            ),
        ),
    )

    assert result.report_intelligence is not None
    definitions = result.report_intelligence.definitions
    assert len(definitions) == 2
    parsed = next(definition for definition in definitions if definition.concept == "PDF")
    opaque = next(definition for definition in definitions if definition is not parsed)
    assert opaque.concept.startswith("Unparsed definition ")
    assert opaque.concept != parsed.concept
    assert opaque.definition == "PDF"


def test_builder_filters_and_sorts_only_contextual_timeline_milestones() -> None:
    """Generic dates vanish while duplicate, evidence-backed milestones merge."""
    result = ReportIntelligenceBuilder().build(_enhanced_report(), _knowledge_objects())
    assert result.report_intelligence is not None
    timeline = result.report_intelligence.timeline

    assert tuple(event.date for event in timeline) == (
        "1993",
        "March 2008",
        "2024-05-10",
    )
    # The most-specific source date wins while same-year duplicate evidence is
    # retained on the one displayed milestone.
    standardized = next(event for event in timeline if event.date == "March 2008")
    assert standardized.supporting_chunk_ids == (_CHUNK_IDS[1], _CHUNK_IDS[2])
    assert standardized.confidence == pytest.approx(0.75)
    assert all(event.date != "2020" for event in timeline)


def test_builder_enriches_authoritative_findings_without_reordering_or_rewriting() -> None:
    """Finding summaries and evidence remain canonical while labels are derived."""
    report = _enhanced_report()
    result = ReportIntelligenceBuilder().build(report, _knowledge_objects())
    assert result.report_intelligence is not None
    findings = result.report_intelligence.findings

    assert tuple((finding.source_kind, finding.source_index) for finding in findings) == (
        ("finding", 0),
        ("finding", 1),
        ("appendix", 0),
    )
    assert findings[0].summary == report.findings[0].description
    assert findings[0].title != report.findings[0].description
    assert findings[1].supporting_chunk_ids == report.findings[1].supporting_chunk_ids
    assert findings[1].confidence == pytest.approx(0.75)
    assert all(
        finding.importance in {"HIGH", "MEDIUM", "LOW"}
        for finding in findings
    )


def test_importance_bands_use_only_public_labels_and_keep_scores_private() -> None:
    """Fixed score thresholds publish no numeric ranking field on findings."""
    builder = ReportIntelligenceBuilder()
    high = builder._score_finding(
        confidence=1.0,
        source_count=4,
        tokens=frozenset({"pdf"}),
        token_frequency=Counter({"pdf": 4}),
        entity_frequency=Counter({"pdf": 5}),
        summary_tokens=frozenset({"pdf"}),
    )
    medium = builder._score_finding(
        confidence=0.875,
        source_count=1,
        tokens=frozenset(),
        token_frequency=Counter(),
        entity_frequency=Counter(),
        summary_tokens=frozenset(),
    )
    low = builder._score_finding(
        confidence=0.0,
        source_count=1,
        tokens=frozenset(),
        token_frequency=Counter(),
        entity_frequency=Counter(),
        summary_tokens=frozenset(),
    )

    assert (high.importance, medium.importance, low.importance) == (
        "HIGH",
        "MEDIUM",
        "LOW",
    )
    assert high.value >= 70
    assert 40 <= medium.value < 70
    assert low.value < 40
    assert "value" not in result_fields()


def result_fields() -> set[str]:
    """Return public enriched-finding fields without exposing private scores."""
    from app.reports import EnrichedFinding

    return set(EnrichedFinding.model_fields)


def test_builder_consolidates_references_and_excludes_orphan_sources() -> None:
    """Displayed references are normalized, sorted, deduplicated, and sourced."""
    result = ReportIntelligenceBuilder().build(_enhanced_report(), _knowledge_objects())
    assert result.report_intelligence is not None
    references = result.report_intelligence.references

    assert tuple(reference.reference for reference in references) == (
        "Alpha Reference",
        "Beta Reference",
        "Gamma Reference",
        "Zeta Reference",
    )
    assert references[0].supporting_chunk_ids == (_CHUNK_IDS[0], _CHUNK_IDS[1])
    assert all(reference.reference != "Orphan Reference" for reference in references)


def test_builder_is_deterministic_and_idempotent_for_identical_input() -> None:
    """Rebuilding an overlay produces equal values without changing base fields."""
    builder = ReportIntelligenceBuilder()
    report = _enhanced_report()
    sources = _knowledge_objects()

    first = builder.build(report, sources)
    second = builder.build(report, sources)
    rebuilt = builder.build(first, sources)

    assert first == second
    assert rebuilt == first
    assert rebuilt.base_report is report.base_report
    assert rebuilt.findings is report.findings


def test_models_are_strict_frozen_and_builder_rejects_invalid_provenance() -> None:
    """Malformed overlays cannot be made renderable through intelligence data."""
    with pytest.raises(ValidationError):
        NormalizedEntity(
            name="PDF",
            aliases=("PDF",),
            supporting_chunk_ids=(_CHUNK_IDS[0],),
            references=(),
            confidence=1.0,
            unexpected=True,
        )
    entity = NormalizedEntity(
        name="PDF",
        aliases=("PDF",),
        supporting_chunk_ids=(_CHUNK_IDS[0],),
        references=(),
        confidence=1.0,
    )
    with pytest.raises(ValidationError):
        entity.name = "Changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ReportIntelligence(
            definitions=(
                ConsolidatedDefinition(
                    concept="PDF",
                    definition="A document format.",
                    supporting_chunk_ids=(_CHUNK_IDS[0],),
                    confidence=1.0,
                ),
                ConsolidatedDefinition(
                    concept="pdf",
                    definition="A duplicate canonical concept.",
                    supporting_chunk_ids=(_CHUNK_IDS[1],),
                    confidence=1.0,
                ),
            )
        )
    with pytest.raises(ValidationError):
        ReportIntelligence(
            references=(
                ConsolidatedReference(
                    reference="Reference",
                    supporting_chunk_ids=(_CHUNK_IDS[0],),
                ),
                ConsolidatedReference(
                    reference="Reference",
                    supporting_chunk_ids=(_CHUNK_IDS[1],),
                ),
            )
        )

    unknown = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    invalid = _enhanced_report().model_copy(
        update={
            "findings": (
                Finding(
                    title="Unknown source",
                    description="This claim does not map to supplied evidence.",
                    supporting_chunk_ids=(unknown,),
                ),
            )
        }
    )
    with pytest.raises(ReportSynthesisError):
        ReportIntelligenceBuilder().build(invalid, _knowledge_objects())
