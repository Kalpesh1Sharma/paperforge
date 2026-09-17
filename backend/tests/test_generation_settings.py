"""Phase 2 configurable report contract tests."""

from pydantic import ValidationError
import pytest

from app.reports import ReportGenerationSettings, ReportMode


def _canonical_payload() -> dict[str, object]:
    return {
        "schema_version": 2,
        "project_title": "Evidence workspace",
        "research_domain": "Responsible AI",
        "purpose": "Prepare an institutional review.",
        "report_structure": {
            "preset": "technical",
            "sections": [
                {"key": "executive-summary", "heading": "Decision Summary"},
                {"key": "abstract", "heading": "Research Abstract"},
            ],
        },
        "content": {
            "tone": "academic",
            "audience": "University review panel",
            "language": "en",
        },
        "visual_theme": {
            "template": "modern-research",
            "page_size": "A4",
            "density": "compact",
            "accent_color": "#315ee8",
        },
        "citations": {"style": "apa", "include_bibliography": True},
        "publication": {
            "title": "Responsible AI Evidence Review",
            "subtitle": "A source-grounded assessment",
            "author": "Kalpesh Sharma",
            "organisation": "PaperForge",
            "university": "MNIT Jaipur",
            "department": "Computer Science",
            "publication_type": "Academic report",
        },
    }


def test_canonical_settings_keep_structure_content_theme_and_citations_separate() -> None:
    settings = ReportGenerationSettings.model_validate(_canonical_payload())

    assert settings.schema_version == 2
    assert settings.structure is ReportMode.TECHNICAL
    assert [section.key for section in settings.report_structure.sections] == [
        "executive-summary",
        "abstract",
    ]
    assert settings.content.tone == "academic"
    assert settings.visual_template == "modern-research"
    assert settings.citations.style == "apa"
    assert settings.publication.university == "MNIT Jaipur"


def test_phase_one_flat_settings_are_migrated_to_schema_version_two() -> None:
    settings = ReportGenerationSettings.model_validate(
        {
            "project_title": "Legacy report",
            "research_domain": "Software Engineering",
            "purpose": None,
            "structure": "professional",
            "visual_template": "editorial",
            "report_title": "Reliable Systems",
            "author": "Kalpesh Sharma",
            "organisation": None,
        }
    )

    payload = settings.model_dump(mode="json")
    assert payload["schema_version"] == 2
    assert payload["publication"]["title"] == "Reliable Systems"
    assert payload["visual_theme"]["template"] == "editorial"
    assert len(payload["report_structure"]["sections"]) == 10


def test_duplicate_sections_and_invalid_accent_colours_are_rejected() -> None:
    duplicate = _canonical_payload()
    duplicate["report_structure"] = {
        "preset": "professional",
        "sections": [
            {"key": "abstract", "heading": "First"},
            {"key": "abstract", "heading": "Second"},
        ],
    }
    with pytest.raises(ValidationError):
        ReportGenerationSettings.model_validate(duplicate)

    invalid_colour = _canonical_payload()
    invalid_colour["visual_theme"] = {
        "template": "minimal",
        "page_size": "A4",
        "density": "comfortable",
        "accent_color": "blue",
    }
    with pytest.raises(ValidationError):
        ReportGenerationSettings.model_validate(invalid_colour)
