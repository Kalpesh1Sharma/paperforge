"""Citation-style projection and bibliography management for presentations."""

from __future__ import annotations

import re

from app.reports.presentation_models import (
    AppendixGroup,
    BibliographyEntry,
    ConceptCard,
    EntityCard,
    EntityPresentationGroup,
    GroupedFinding,
    InsightCard,
    PresentationEvidence,
    PresentationModel,
    PresentationSection,
    ReferenceCard,
    TimelineCard,
)

_PAGE_LABEL = re.compile(r"^(?P<title>.+?) · (?P<locator>p{1,2}\. .+|excerpt \d+)$")


def apply_citation_style(
    presentation: PresentationModel,
    *,
    style: str,
    include_bibliography: bool,
) -> PresentationModel:
    """Format inline provenance and construct one deduplicated bibliography."""
    labels = _ordered_labels(presentation)
    sources = tuple(dict.fromkeys(_parts(label)[0] for label in labels))
    source_numbers = {source: index for index, source in enumerate(sources, start=1)}
    numbers = {label: source_numbers[_parts(label)[0]] for label in labels}
    sections = tuple(_format_section(section, style, numbers) for section in presentation.sections)
    bibliography = (
        tuple(
            _bibliography_entry(source, style, source_numbers[source])
            for source in sources
        )
        if include_bibliography
        else ()
    )
    return presentation.model_copy(
        update={
            "citation_style": style,
            "sections": sections,
            "bibliography": bibliography,
        }
    )


def _ordered_labels(presentation: PresentationModel) -> tuple[str, ...]:
    labels: list[str] = []
    seen: set[str] = set()
    for section in presentation.sections:
        for evidence in _section_evidence(section):
            for label in evidence.source_labels:
                if label not in seen:
                    seen.add(label)
                    labels.append(label)
    return tuple(labels)


def _section_evidence(section: PresentationSection) -> tuple[PresentationEvidence, ...]:
    evidence: list[PresentationEvidence] = []
    for group in section.finding_groups:
        evidence.extend(item.evidence for item in group.findings)
    evidence.extend(item.evidence for item in section.concepts)
    for group in section.entity_groups:
        evidence.extend(item.evidence for item in group.entities)
    evidence.extend(item.evidence for item in section.timeline)
    evidence.extend(item.evidence for item in section.references)
    for appendix in section.appendix_groups:
        evidence.extend(item.evidence for item in appendix.findings)
        evidence.extend(item.evidence for item in appendix.concepts)
        for group in appendix.entities:
            evidence.extend(item.evidence for item in group.entities)
        evidence.extend(item.evidence for item in appendix.references)
    return tuple(evidence)


def _inline(label: str, style: str, number: int) -> str:
    title, locator = _parts(label)
    if style == "ieee":
        return f"[{number}{', ' + locator if locator else ''}]"
    if style == "apa":
        return f"({title}, n.d.{_inline_locator(locator)})"
    if style == "harvard":
        return f"({title} n.d.{_inline_locator(locator)})"
    return label


def _inline_locator(locator: str | None) -> str:
    if locator is None:
        return ""
    if locator.startswith("excerpt"):
        return f", {locator}"
    return f", {locator}"


def _parts(label: str) -> tuple[str, str | None]:
    match = _PAGE_LABEL.match(label)
    return (match.group("title"), match.group("locator")) if match else (label, None)


def _bibliography_entry(title: str, style: str, number: int) -> BibliographyEntry:
    if style == "ieee":
        citation = f"[{number}] {title}."
    elif style == "apa":
        citation = f"{title}. (n.d.). Source document."
    elif style == "harvard":
        citation = f"{title} (n.d.) Source document."
    else:
        citation = f"{number}. {title}."
    return BibliographyEntry(number=number, source_label=title, citation=citation)


def _evidence(value: PresentationEvidence, style: str, numbers: dict[str, int]) -> PresentationEvidence:
    return value.model_copy(
        update={
            "source_labels": tuple(
                _inline(label, style, numbers[label]) for label in value.source_labels
            )
        }
    )


def _finding(value: InsightCard, style: str, numbers: dict[str, int]) -> InsightCard:
    return value.model_copy(update={"evidence": _evidence(value.evidence, style, numbers)})


def _concept(value: ConceptCard, style: str, numbers: dict[str, int]) -> ConceptCard:
    return value.model_copy(update={"evidence": _evidence(value.evidence, style, numbers)})


def _entity(value: EntityCard, style: str, numbers: dict[str, int]) -> EntityCard:
    return value.model_copy(update={"evidence": _evidence(value.evidence, style, numbers)})


def _entity_group(value: EntityPresentationGroup, style: str, numbers: dict[str, int]) -> EntityPresentationGroup:
    return value.model_copy(update={"entities": tuple(_entity(item, style, numbers) for item in value.entities)})


def _reference(value: ReferenceCard, style: str, numbers: dict[str, int]) -> ReferenceCard:
    return value.model_copy(update={"evidence": _evidence(value.evidence, style, numbers)})


def _timeline(value: TimelineCard, style: str, numbers: dict[str, int]) -> TimelineCard:
    return value.model_copy(update={"evidence": _evidence(value.evidence, style, numbers)})


def _appendix(value: AppendixGroup, style: str, numbers: dict[str, int]) -> AppendixGroup:
    return value.model_copy(update={
        "findings": tuple(_finding(item, style, numbers) for item in value.findings),
        "concepts": tuple(_concept(item, style, numbers) for item in value.concepts),
        "entities": tuple(_entity_group(item, style, numbers) for item in value.entities),
        "references": tuple(_reference(item, style, numbers) for item in value.references),
    })


def _format_section(section: PresentationSection, style: str, numbers: dict[str, int]) -> PresentationSection:
    return section.model_copy(update={
        "finding_groups": tuple(group.model_copy(update={"findings": tuple(_finding(item, style, numbers) for item in group.findings)}) for group in section.finding_groups),
        "concepts": tuple(_concept(item, style, numbers) for item in section.concepts),
        "entity_groups": tuple(_entity_group(item, style, numbers) for item in section.entity_groups),
        "timeline": tuple(_timeline(item, style, numbers) for item in section.timeline),
        "references": tuple(_reference(item, style, numbers) for item in section.references),
        "appendix_groups": tuple(_appendix(item, style, numbers) for item in section.appendix_groups),
    })
