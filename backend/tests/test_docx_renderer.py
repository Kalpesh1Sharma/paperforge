"""Editable DOCX export coverage."""

from pathlib import Path

from docx import Document

from app.reports.docx_renderer import EditableDocxRenderer
from app.reports.presentation_models import BibliographyEntry
from tests.test_citation_quality import _presentation


def test_editable_docx_contains_report_content_and_bibliography(tmp_path: Path) -> None:
    presentation = _presentation().model_copy(
        update={
            "citation_style": "ieee",
            "bibliography": (
                BibliographyEntry(
                    number=1,
                    source_label="research.pdf",
                    citation="[1] research.pdf.",
                ),
            ),
        }
    )
    output = tmp_path / "report.docx"

    EditableDocxRenderer().render_presentation(presentation, output)

    document = Document(output)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert output.read_bytes().startswith(b"PK")
    assert "Grounded report" in text
    assert "Major Findings" in text
    assert "The source records a measurable result." in text
    assert "Bibliography" in text
    assert "[1] research.pdf." in text
    assert document.core_properties.title == "Grounded report"
