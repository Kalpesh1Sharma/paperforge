"""Focused tests for persisted Batch 9 section editing helpers."""

from app.reports.editor import SectionTransformer, editable_section_text
from app.reports.presentation_models import PresentationSection


def test_editor_prefers_user_content_over_generated_blocks() -> None:
    section = PresentationSection(
        key="abstract",
        heading="Abstract",
        anchor_id="abstract",
        intro=("Generated source-grounded prose.",),
        edited_content="  User-approved replacement.  ",
        locked=True,
    )

    assert editable_section_text(section) == "User-approved replacement."


def test_deterministic_shorten_reduces_content_without_adding_claims() -> None:
    source = "First supported claim. Second supported claim. Third supported claim."

    shortened = SectionTransformer._deterministic(source, "shorten")

    assert shortened == "First supported claim. Second supported claim."
    assert len(shortened) < len(source)


def test_deterministic_rewrite_normalizes_spacing_without_inventing_text() -> None:
    source = "  Supported   sentence.\n\n  Another supported sentence.  "

    rewritten = SectionTransformer._deterministic(source, "rewrite")

    assert rewritten == "Supported sentence.\n\nAnother supported sentence."
