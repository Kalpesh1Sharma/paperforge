"""Plain-text document parser."""

from pathlib import Path

from app.models.parsed_document import ParsedDocument
from app.parsers.base import BaseParser, FileAccessError, TextDecodingError


class UTF8TextParser(BaseParser):
    """Shared BOM-safe UTF-8 implementation for text-based formats."""

    def _parse_utf8_file(self, file_path: Path) -> ParsedDocument:
        """Read only the final required text representation from disk."""
        path = self._validate_file_path(file_path)

        try:
            with path.open("r", encoding="utf-8-sig", newline="") as source_file:
                extracted_text = source_file.read()
        except UnicodeDecodeError as exc:
            raise TextDecodingError(
                f"Document is not valid UTF-8 text: '{path.name}'."
            ) from exc
        except OSError as exc:
            raise FileAccessError(f"Unable to read document: '{path.name}'.") from exc

        return self._build_document(file_path=path, extracted_text=extracted_text)


class TextParser(UTF8TextParser):
    """Preserve UTF-8 plain-text source as extracted text."""

    file_type = "txt"

    def parse(self, file_path: Path) -> ParsedDocument:
        """Extract plain text without normalization."""
        return self._parse_utf8_file(file_path)
