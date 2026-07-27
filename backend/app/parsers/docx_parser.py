"""DOCX text extraction with python-docx."""

from datetime import datetime
from pathlib import Path
from typing import Iterator
from zipfile import BadZipFile

from docx import Document as load_document
from docx.document import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.models.parsed_document import MetadataValue, ParsedDocument
from app.parsers.base import BaseParser, DOCXParsingError


class DocxParser(BaseParser):
    """Extract DOCX body text and core document metadata."""

    file_type = "docx"

    def parse(self, file_path: Path) -> ParsedDocument:
        """Read a DOCX from its path without separately buffering file bytes."""
        path = self._validate_file_path(file_path)

        try:
            with self._create_text_buffer() as text_buffer:
                document = load_document(path)
                has_content = False
                for block_text in self._iter_body_text(document):
                    if not block_text:
                        continue
                    if has_content:
                        text_buffer.write("\n")
                    text_buffer.write(block_text)
                    has_content = True
                metadata = self._extract_metadata(document)

                text_buffer.seek(0)
                extracted_text = text_buffer.read()
        except (BadZipFile, OSError, PackageNotFoundError, ValueError) as exc:
            raise DOCXParsingError(f"Unable to parse DOCX: '{path.name}'.") from exc

        return self._build_document(
            file_path=path,
            extracted_text=extracted_text,
            metadata=metadata,
        )

    def _iter_body_text(self, document: DocxDocument) -> Iterator[str]:
        """Yield paragraphs and table rows in document-body order."""
        for child in document.element.body.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, document).text
            elif isinstance(child, CT_Tbl):
                table = Table(child, document)
                for row in table.rows:
                    yield "\t".join(cell.text for cell in row.cells)

    def _extract_metadata(self, document: DocxDocument) -> dict[str, MetadataValue]:
        """Return serializable non-empty python-docx core properties."""
        property_names = (
            "author",
            "category",
            "comments",
            "content_status",
            "created",
            "identifier",
            "keywords",
            "language",
            "last_modified_by",
            "last_printed",
            "modified",
            "revision",
            "subject",
            "title",
            "version",
        )
        metadata: dict[str, MetadataValue] = {}

        for property_name in property_names:
            value = getattr(document.core_properties, property_name, None)
            if value in (None, ""):
                continue
            if isinstance(value, datetime):
                metadata[property_name] = value.isoformat()
            elif isinstance(value, (str, int, float, bool)):
                metadata[property_name] = value
            else:
                metadata[property_name] = str(value)

        return metadata
