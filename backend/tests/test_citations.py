"""Tests for deterministic human-readable enhanced-report citations."""

from uuid import UUID

from app.reports import (
    EnhancedResearchReport,
    Finding,
    MarkdownRenderer,
    ResearchReport,
    SynthesisMetadata,
    SynthesisSourceEvidence,
    SynthesizedSection,
    TimelineEvent,
)
from app.reports.citations import CitationIndex


_FIRST = UUID("11111111-1111-1111-1111-111111111111")
_SECOND = UUID("22222222-2222-2222-2222-222222222222")


def _base_report() -> ResearchReport:
    """Build a small immutable base report for citation-only tests."""
    return ResearchReport(
        title="Research Report",
        executive_summary="Base summary.",
        findings=(),
        important_entities=(),
        important_definitions=(),
        important_metrics=(),
        timeline=(
            TimelineEvent(
                date="2026",
                description="Extracted date: 2026.",
                supporting_chunk_ids=(_FIRST,),
            ),
        ),
        references=("Legacy reference",),
        sections=(),
    )


def test_evidence_order_defines_source_labels_and_references() -> None:
    """Source labels follow knowledge-object evidence order, not UUID values."""
    report = EnhancedResearchReport(
        base_report=_base_report(),
        executive_summary="Enhanced summary.",
        findings=(
            Finding(
                title="Finding",
                description="Supported fact.",
                supporting_chunk_ids=(_FIRST, _SECOND),
            ),
        ),
        appendix_findings=(),
        sections=(),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=_SECOND,
                    confidence=0.8,
                    references=("Second source",),
                ),
                SynthesisSourceEvidence(
                    chunk_id=_FIRST,
                    confidence=0.9,
                    references=("First source",),
                ),
            ),
        ),
    )

    index = CitationIndex.from_report(report)

    assert index.labels_for((_FIRST, _SECOND)) == ("Source 2", "Source 1")
    assert index.sources[0].label == "Source 1"
    assert index.sources[0].references == ("Second source",)
    assert index.sources[1].label == "Source 2"
    assert index.sources[1].references == ("First source",)


def test_legacy_reports_use_first_rendered_chunk_order_without_uuid_output() -> None:
    """Old manually constructed overlays receive deterministic labels too."""
    report = EnhancedResearchReport(
        base_report=_base_report(),
        executive_summary="Enhanced summary.",
        findings=(
            Finding(
                title="Finding",
                description="Supported fact.",
                supporting_chunk_ids=(_SECOND,),
            ),
        ),
        appendix_findings=(
            Finding(
                title="Appendix",
                description="Additional supported fact.",
                supporting_chunk_ids=(_FIRST,),
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

    index = CitationIndex.from_report(report)

    assert index.labels_for((_SECOND,)) == ("Source 1",)
    assert index.labels_for((_FIRST,)) == ("Source 2",)
    assert index.sources[0].references == ("Legacy reference",)


def test_markdown_cites_each_claim_with_source_evidence_order() -> None:
    """All claim-bearing enhanced content uses stable labels instead of UUIDs."""
    report = EnhancedResearchReport(
        base_report=_base_report(),
        executive_summary="Enhanced summary.",
        findings=(
            Finding(
                title="Primary finding",
                description="A supported primary claim.",
                supporting_chunk_ids=(_FIRST, _SECOND),
            ),
        ),
        appendix_findings=(
            Finding(
                title="Appendix finding",
                description="A supported appendix claim.",
                supporting_chunk_ids=(_SECOND,),
            ),
        ),
        sections=(
            SynthesizedSection(
                heading="Thematic section",
                content="A supported thematic claim.",
                supporting_chunk_ids=(_FIRST,),
            ),
        ),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=_SECOND,
                    confidence=0.8,
                    references=("Second source",),
                ),
                SynthesisSourceEvidence(
                    chunk_id=_FIRST,
                    confidence=0.9,
                    references=("First source",),
                ),
            ),
        ),
    )

    markdown = MarkdownRenderer().render_enhanced(report)

    assert "#### Primary finding" in markdown
    assert "A supported primary claim." in markdown
    assert "*Evidence: 2 sources; Sources: Source 2, Source 1*" in markdown
    assert "### 2026" in markdown
    assert "Document records the date 2026." in markdown
    assert "#### Thematic section" in markdown
    assert "A supported thematic claim." in markdown
    assert "#### Appendix finding" in markdown
    assert "A supported appendix claim." in markdown
    assert "1. Second source [Source 1]" in markdown
    assert "2. First source [Source 2]" in markdown
    assert str(_FIRST) not in markdown
    assert str(_SECOND) not in markdown
