"""Deterministic report completeness, support, and formatting checks."""

from __future__ import annotations

from app.reports.presentation_models import (
    PresentationEvidence,
    PresentationModel,
    PresentationSection,
    QualityIssue,
    ReportQuality,
)


def check_report_quality(
    presentation: PresentationModel,
    *,
    bibliography_required: bool,
) -> PresentationModel:
    """Attach actionable checks without mutating report prose or provenance."""
    issues: list[QualityIssue] = []
    checked = 0
    supported = 0
    for section in presentation.sections:
        if not _has_visible_content(section):
            issues.append(QualityIssue(
                code="missing-section",
                severity="warning",
                section_key=section.key,
                message=f"{section.heading} has no evidence-backed content.",
            ))
        if len(section.heading) > 100:
            issues.append(QualityIssue(
                code="formatting",
                severity="warning",
                section_key=section.key,
                message=f"{section.heading[:60]} has an unusually long heading.",
            ))
        for evidence in _claim_evidence(section):
            checked += 1
            if evidence.supporting_chunk_ids:
                supported += 1
            else:
                issues.append(QualityIssue(
                    code="unsupported-claim",
                    severity="warning",
                    section_key=section.key,
                    message=f"Review a claim in {section.heading}; no source excerpt is linked.",
                ))
    if bibliography_required and checked and not presentation.bibliography:
        issues.append(QualityIssue(
            code="missing-bibliography",
            severity="error",
            message="A bibliography is required but no source entries were generated.",
        ))
    if len(presentation.cover.title) > 160:
        issues.append(QualityIssue(
            code="formatting",
            severity="warning",
            message="The report title may be too long for a clean publication cover.",
        ))
    unique = tuple(dict.fromkeys(issues))
    status = "blocked" if any(issue.severity == "error" for issue in unique) else "warnings" if unique else "passed"
    quality = ReportQuality(status=status, checked_claims=checked, supported_claims=supported, issues=unique)
    return presentation.model_copy(update={"quality": quality})


def _has_visible_content(section: PresentationSection) -> bool:
    return bool(
        section.edited_content
        or section.intro
        or section.finding_groups
        or section.concepts
        or section.entity_groups
        or section.timeline
        or section.evidence_tables
        or section.appendix_groups
        or section.references
    )


def _claim_evidence(section: PresentationSection) -> tuple[PresentationEvidence, ...]:
    evidence: list[PresentationEvidence] = []
    for group in section.finding_groups:
        evidence.extend(item.evidence for item in group.findings)
    evidence.extend(item.evidence for item in section.concepts)
    for group in section.entity_groups:
        evidence.extend(item.evidence for item in group.entities)
    evidence.extend(item.evidence for item in section.timeline)
    for appendix in section.appendix_groups:
        evidence.extend(item.evidence for item in appendix.findings)
        evidence.extend(item.evidence for item in appendix.concepts)
        for group in appendix.entities:
            evidence.extend(item.evidence for item in group.entities)
    return tuple(evidence)
