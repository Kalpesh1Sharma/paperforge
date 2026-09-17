"""Efficient page-by-page PDF text extraction using PyMuPDF."""

from pathlib import Path

import pymupdf

from app.models.parsed_document import ParsedDocument, ParsedPageSpan
from app.parsers.base import BaseParser, PDFParsingError


class PDFParser(BaseParser):
    """Extract PDF text and metadata without reading the raw file into memory."""

    file_type = "pdf"

    def parse(self, file_path: Path) -> ParsedDocument:
        """Extract each PDF page in turn and return a unified document result."""
        path = self._validate_file_path(file_path)

        try:
            with self._create_text_buffer() as text_buffer:
                with pymupdf.open(path) as document:
                    if document.needs_pass:
                        raise PDFParsingError(
                            "Password-protected PDFs are not supported: "
                            f"'{path.name}'."
                        )

                    page_spans: list[ParsedPageSpan] = []
                    for page_index, page in enumerate(document):
                        if page_index:
                            text_buffer.write("\n")
                        start_char = text_buffer.tell()
                        page_text = page.get_text("text")
                        text_buffer.write(page_text)
                        page_spans.append(
                            ParsedPageSpan(
                                page_number=page_index + 1,
                                start_char=start_char,
                                end_char=start_char + len(page_text),
                            )
                        )

                    metadata = {
                        key: str(value)
                        for key, value in document.metadata.items()
                        if value not in (None, "")
                    }
                    page_count = document.page_count

                text_buffer.seek(0)
                extracted_text = text_buffer.read()
        except PDFParsingError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise PDFParsingError(f"Unable to parse PDF: '{path.name}'.") from exc

        parsed = self._build_document(
            file_path=path,
            extracted_text=extracted_text,
            page_count=page_count,
            metadata=metadata,
        )
        return parsed.model_copy(update={"pages": tuple(page_spans)})
