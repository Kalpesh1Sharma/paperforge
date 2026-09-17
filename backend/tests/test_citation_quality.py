"""Citation projection and deterministic report-quality checks."""

from datetime import date
from uuid import UUID

import pytest

from app.reports.citation_styles import apply_citation_style
from app.reports.presentation_models import (
    DocumentMetadata,
    GroupedFinding,
    InsightCard,
    PresentationEvidence,
    PresentationModel,
    PresentationSection,
    TableOfContents,
    TableOfContentsEntry,
)
from app.reports.quality import check_report_quality

_ONE = UUID("11111111-1111-1111-1111-111111111111")
_TWO = UUID("22222222-2222-2222-2222-222222222222")


def _presentation(*, supported: bool = True) -> PresentationModel:
    ids = (_ONE, _TWO) if supported else ()
    labels = ("research.pdf · p. 2", "research.pdf · p. 5") if supported else ()
    evidence = PresentationEvidence(
        supporting_chunk_ids=ids,
        source_labels=labels,
        source_count=len(ids),
    )
    section = PresentationSection(
        key="key-insights",
        heading="Major Findings",
        anchor_id="key-insights",
        finding_groups=(
            GroupedFinding(
                heading="General",
                findings=(
                    InsightCard(
                        key="finding-1",
                        title="A supported claim",
                        summary="The source records a measurable result.",
                        evidence=evidence,
                    ),
                ),
            ),
        ),
    )
    return PresentationModel(
        cover=DocumentMetadata(
            title="Grounded report",
            filename="research.pdf",
            file_type="pdf",
            page_count=5,
            generated_on=date(2026, 9, 11),
            knowledge_object_count=1,
            evidence_source_count=len(ids),
            status="AI-enhanced",
            domain="Software Engineering",
        ),
        table_of_contents=TableOfContents(
            entries=(TableOfContentsEntry(heading=section.heading, anchor_id=section.anchor_id),)
        ),
        sections=(section,),
    )


@pytest.mark.parametrize(
    ("style", "expected_inline", "expected_reference"),
    [
        ("apa", "(research.pdf, n.d., p. 2)", "research.pdf. (n.d.). Source document."),
        ("ieee", "[1, p. 2]", "[1] research.pdf."),
        ("harvard", "(research.pdf n.d., p. 2)", "research.pdf (n.d.) Source document."),
    ],
)
def test_citation_styles_share_one_bibliography_entry_per_document(
    style: str,
    expected_inline: str,
    expected_reference: str,
) -> None:
    formatted = apply_citation_style(
        _presentation(), style=style, include_bibliography=True
    )

    evidence = formatted.sections[0].finding_groups[0].findings[0].evidence
    assert evidence.source_labels[0] == expected_inline
    assert len(formatted.bibliography) == 1
    assert formatted.bibliography[0].citation == expected_reference


def test_quality_check_counts_support_and_warns_for_unlinked_claims() -> None:
    supported = check_report_quality(_presentation(), bibliography_required=False)
    unsupported = check_report_quality(
        _presentation(supported=False), bibliography_required=False
    )

    assert supported.quality.status == "passed"
    assert (supported.quality.checked_claims, supported.quality.supported_claims) == (1, 1)
    assert unsupported.quality.status == "warnings"
    assert unsupported.quality.issues[0].code == "unsupported-claim"


def test_required_bibliography_can_block_quality_check() -> None:
    checked = check_report_quality(_presentation(), bibliography_required=True)

    assert checked.quality.status == "blocked"
    assert any(issue.code == "missing-bibliography" for issue in checked.quality.issues)
