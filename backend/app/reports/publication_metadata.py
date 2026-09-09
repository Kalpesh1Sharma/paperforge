"""Shared publication copy derived from presentation metadata."""

from app.reports.presentation_models import DocumentMetadata


def document_overview_intro(cover: DocumentMetadata) -> tuple[str, ...]:
    """Describe source metadata using the same values shown on the cover."""
    type_text = cover.file_type or "Not available"
    page_text = (
        str(cover.page_count) if cover.page_count is not None else "Not available"
    )
    return (
        "This overview establishes the document's subject area and the "
        "available publication details.",
        f"The document is classified in {cover.domain}; source type: "
        f"{type_text}; page count: {page_text}.",
    )
