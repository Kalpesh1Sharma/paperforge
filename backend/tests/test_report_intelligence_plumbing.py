"""Tests for the optional report-intelligence overlay integration."""

from copy import deepcopy
from uuid import UUID

from app.knowledge import KnowledgeObject
from app.reports import (
    ConsolidatedDefinition,
    ConsolidatedReference,
    EnhancedResearchReport,
    EnrichedFinding,
    EntityGroup,
    Finding,
    IntelligentTimelineEvent,
    NormalizedEntity,
    ReportIntelligence,
    ReportIntelligenceBuilder,
    ResearchReport,
    SynthesisMetadata,
)

_CHUNK_ID = UUID("12345678-1234-5678-1234-567812345678")


def test_report_intelligence_primitives_are_publicly_exported() -> None:
    """Consumers can import each supported intelligence primitive from reports."""
    exported_types = (
        ReportIntelligence,
        NormalizedEntity,
        EntityGroup,
        ConsolidatedDefinition,
        IntelligentTimelineEvent,
        EnrichedFinding,
        ConsolidatedReference,
        ReportIntelligenceBuilder,
    )

    assert all(isinstance(exported_type, type) for exported_type in exported_types)


def _enhanced_report() -> EnhancedResearchReport:
    """Build a valid pre-intelligence overlay using the legacy constructor."""
    return EnhancedResearchReport(
        base_report=ResearchReport(
            title="Research Report",
            executive_summary="Deterministic report summary.",
            findings=(
                Finding(
                    title="Latency improvement",
                    description="The service improved latency by 95%.",
                    supporting_chunk_ids=(_CHUNK_ID,),
                ),
            ),
            important_entities=("PaperForge",),
            important_definitions=("Latency is response time.",),
            important_metrics=("95%",),
            timeline=(),
            references=("https://example.com/source",),
            sections=(),
        ),
        executive_summary=(
            "The source describes backend engineering work.\n\n"
            "It records a measurable latency improvement."
        ),
        findings=(
            Finding(
                title="Latency improvement",
                description="The service improved latency by 95%.",
                supporting_chunk_ids=(_CHUNK_ID,),
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


def _knowledge_objects() -> tuple[KnowledgeObject, ...]:
    """Build deterministic source knowledge for the explicit enrichment stage."""
    return (
        KnowledgeObject(
            chunk_id=_CHUNK_ID,
            entities=("PaperForge",),
            facts=("The service improved latency by 95%.",),
            definitions=("Latency is response time.",),
            metrics=("95%",),
            dates=("2026-07-30",),
            references=("https://example.com/source",),
            confidence=1.0,
        ),
    )


def test_enhanced_report_remains_backward_compatible_without_intelligence() -> None:
    """Legacy EnhancedResearchReport construction keeps the new field empty."""
    report = _enhanced_report()

    assert report.report_intelligence is None


def test_intelligence_builder_is_an_explicit_immutable_enrichment_stage() -> None:
    """The builder adds intelligence without changing canonical report fields."""
    report = _enhanced_report()
    knowledge_objects = _knowledge_objects()
    report_before = deepcopy(report.model_dump(mode="python"))
    knowledge_before = deepcopy(
        tuple(
            knowledge_object.model_dump(mode="python")
            for knowledge_object in knowledge_objects
        )
    )

    enriched_report = ReportIntelligenceBuilder().build(report, knowledge_objects)

    assert enriched_report is not report
    assert enriched_report.base_report is report.base_report
    assert enriched_report.executive_summary is report.executive_summary
    assert enriched_report.findings is report.findings
    assert enriched_report.appendix_findings is report.appendix_findings
    assert enriched_report.sections is report.sections
    assert enriched_report.synthesis_metadata is report.synthesis_metadata
    assert enriched_report.report_intelligence is not None
    assert report.report_intelligence is None
    assert report.model_dump(mode="python") == report_before
    assert tuple(
        knowledge_object.model_dump(mode="python")
        for knowledge_object in knowledge_objects
    ) == knowledge_before
