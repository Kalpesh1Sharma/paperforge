"""Tests for deterministic report refinement without AI or external services."""

from uuid import UUID, uuid4

import pytest

from app.knowledge import KnowledgeObject
from app.reports import Finding, ResearchReport
from app.reports.refinement import (
    CandidateRewrite,
    InvalidRefinementRewriteError,
    ReportRefiner,
)


def _knowledge(
    chunk_id: UUID,
    *,
    confidence: float = 1.0,
    entities: tuple[str, ...] = (),
    metrics: tuple[str, ...] = (),
    dates: tuple[str, ...] = (),
    definitions: tuple[str, ...] = (),
    references: tuple[str, ...] = (),
) -> KnowledgeObject:
    """Build an immutable source evidence fixture."""
    return KnowledgeObject(
        chunk_id=chunk_id,
        entities=entities,
        facts=(),
        definitions=definitions,
        metrics=metrics,
        dates=dates,
        references=references,
        confidence=confidence,
    )


def _report(
    findings: tuple[Finding, ...],
    *,
    entities: tuple[str, ...] = (),
    metrics: tuple[str, ...] = (),
    dates: tuple[str, ...] = (),
    definitions: tuple[str, ...] = (),
) -> ResearchReport:
    """Build the canonical immutable report used as refiner input."""
    return ResearchReport(
        title="Research Report",
        executive_summary="Research report generated from 2 extracted knowledge objects.",
        findings=findings,
        important_entities=entities,
        important_definitions=definitions,
        important_metrics=metrics,
        timeline=tuple(),
        references=tuple(),
        sections=tuple(),
    )


def test_refiner_merges_exact_and_conservative_lexical_duplicates() -> None:
    """Equivalent facts merge while meaningfully different facts remain separate."""
    first_id = uuid4()
    second_id = uuid4()
    third_id = uuid4()
    report = _report(
        (
            Finding(
                title="Finding 1",
                description="The platform improved API latency by thirty percent.",
                supporting_chunk_ids=(first_id,),
            ),
            Finding(
                title="Finding 2",
                description="Platform improved API latency by thirty percent.",
                supporting_chunk_ids=(second_id,),
            ),
            Finding(
                title="Finding 3",
                description="The platform improved API throughput by fifty percent.",
                supporting_chunk_ids=(third_id,),
            ),
        )
    )

    plan = ReportRefiner.build_plan(
        report,
        (
            _knowledge(first_id, confidence=0.5),
            _knowledge(second_id, confidence=0.9),
            _knowledge(third_id, confidence=0.7),
        ),
    )

    assert len(plan.candidates) == 2
    merged = next(
        candidate
        for candidate in plan.candidates
        if candidate.finding.supporting_chunk_ids == (first_id, second_id)
    )
    assert merged.finding.title == "Platform improved API latency by thirty percent"
    assert merged.finding.description == (
        "Platform improved API latency by thirty percent."
    )
    assert plan.source_evidence[0].chunk_id == first_id
    assert plan.source_evidence[1].chunk_id == second_id


def test_refiner_does_not_merge_similar_but_insufficiently_overlapping_facts() -> None:
    """Lexical grouping stays conservative below the documented threshold."""
    first_id = uuid4()
    second_id = uuid4()
    report = _report(
        (
            Finding(
                title="Finding 1",
                description="The platform improved API latency by thirty percent.",
                supporting_chunk_ids=(first_id,),
            ),
            Finding(
                title="Finding 2",
                description="The platform improved API throughput by thirty percent.",
                supporting_chunk_ids=(second_id,),
            ),
        )
    )

    plan = ReportRefiner.build_plan(
        report,
        (_knowledge(first_id), _knowledge(second_id)),
    )

    assert len(plan.candidates) == 2
    assert plan.findings[0].supporting_chunk_ids == (first_id,)
    assert plan.findings[1].supporting_chunk_ids == (second_id,)


def test_refiner_selects_the_best_source_wording_and_preserves_evidence() -> None:
    """Merged wording follows confidence, then detail, without losing evidence."""
    first_id = uuid4()
    second_id = uuid4()
    report = _report(
        (
            Finding(
                title="Finding 1",
                description="The service reduced latency.",
                supporting_chunk_ids=(first_id,),
            ),
            Finding(
                title="Finding 2",
                description="The service  reduced latency.",
                supporting_chunk_ids=(second_id,),
            ),
        )
    )

    plan = ReportRefiner.build_plan(
        report,
        (
            _knowledge(
                first_id,
                confidence=0.9,
                references=("First reference",),
            ),
            _knowledge(
                second_id,
                confidence=0.9,
                references=("Second reference",),
            ),
        ),
    )

    candidate = plan.candidates[0]
    assert candidate.finding.description == "The service  reduced latency."
    assert candidate.finding.title == "The service  reduced latency"
    assert candidate.finding.supporting_chunk_ids == (first_id, second_id)
    assert plan.source_evidence[0].confidence == 0.9
    assert plan.source_evidence[0].references == ("First reference",)
    assert plan.source_evidence[1].references == ("Second reference",)


def test_refiner_uses_stable_ranking_and_partitions_the_appendix() -> None:
    """Ranking is deterministic, ties retain source order, and only ten lead."""
    chunk_ids = tuple(uuid4() for _ in range(12))
    findings = tuple(
        Finding(
            title=f"Finding {index + 1}",
            description=f"Distinct supported fact {index + 1}.",
            supporting_chunk_ids=(chunk_id,),
        )
        for index, chunk_id in enumerate(chunk_ids)
    )
    knowledge = tuple(
        _knowledge(
            chunk_id,
            confidence=1.0 if index == 11 else 0.5,
            metrics=("95%",) if index == 10 else (),
        )
        for index, chunk_id in enumerate(chunk_ids)
    )

    first = ReportRefiner.build_plan(_report(findings), knowledge)
    second = ReportRefiner.build_plan(_report(findings), knowledge)

    assert first == second
    assert len(first.findings) == 10
    assert len(first.appendix_findings) == 2
    assert first.findings[0].supporting_chunk_ids == (chunk_ids[11],)
    assert first.findings[1].supporting_chunk_ids == (chunk_ids[10],)
    assert first.appendix_findings[0].supporting_chunk_ids == (chunk_ids[8],)
    assert first.appendix_findings[1].supporting_chunk_ids == (chunk_ids[9],)


def test_refiner_builds_content_aware_summary_without_object_count_placeholder() -> None:
    """Fallback summary is factual and never repeats the old generic template."""
    chunk_id = uuid4()
    report = _report(
        (
            Finding(
                title="Finding 1",
                description="The service reduced latency by 30%.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
        entities=("PaperForge",),
        metrics=("30%",),
        dates=("2026-07-29",),
        definitions=("Latency is response time.",),
    )

    plan = ReportRefiner.build_plan(
        report,
        (
            _knowledge(
                chunk_id,
                entities=("PaperForge",),
                metrics=("30%",),
                dates=("2026-07-29",),
                definitions=("Latency is response time.",),
            ),
        ),
    )

    assert "generated from" not in plan.executive_summary
    assert "PaperForge" in plan.executive_summary
    assert "30%" in plan.executive_summary
    assert "Latency is response time." in plan.executive_summary
    assert ".." not in plan.executive_summary


def test_refiner_applies_only_exact_provenance_ai_rewrites() -> None:
    """Rewording can improve wording but cannot change canonical evidence."""
    chunk_id = uuid4()
    plan = ReportRefiner.build_plan(
        _report(
            (
                Finding(
                    title="Finding 1",
                    description="The service reduced latency.",
                    supporting_chunk_ids=(chunk_id,),
                ),
            )
        ),
        (_knowledge(chunk_id),),
    )
    candidate = plan.candidates[0]

    findings, appendix = ReportRefiner.apply_rewrites(
        plan,
        (
            CandidateRewrite(
                candidate_id=candidate.candidate_id,
                title="Latency improvement",
                description="The service reduced latency in production.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
    )

    assert findings[0].title == "Latency improvement"
    assert findings[0].supporting_chunk_ids == (chunk_id,)
    assert appendix == ()
    with pytest.raises(InvalidRefinementRewriteError):
        ReportRefiner.apply_rewrites(
            plan,
            (
                CandidateRewrite(
                    candidate_id=candidate.candidate_id,
                    title="Invalid",
                    description="Invalid source membership.",
                    supporting_chunk_ids=(uuid4(),),
                ),
            ),
        )
