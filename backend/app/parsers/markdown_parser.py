"""Markdown document parser."""

from pathlib import Path

from app.models.parsed_document import ParsedDocument
from app.parsers.text_parser import UTF8TextParser


class MarkdownParser(UTF8TextParser):
    """Preserve UTF-8 Markdown source as extracted text."""

    file_type = "md"

    def parse(self, file_path: Path) -> ParsedDocument:
        """Extract Markdown source without rendering or normalization."""
        return self._parse_utf8_file(file_path)
