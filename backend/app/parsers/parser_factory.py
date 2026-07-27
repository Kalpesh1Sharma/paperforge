"""Factory for selecting a parser from a document file extension."""

from pathlib import Path
from typing import ClassVar

from app.models.parsed_document import ParsedDocument
from app.parsers.base import BaseParser, UnsupportedFileTypeError
from app.parsers.docx_parser import DocxParser
from app.parsers.markdown_parser import MarkdownParser
from app.parsers.pdf_parser import PDFParser
from app.parsers.text_parser import TextParser


class ParserFactory:
    """Select the appropriate parser for the supported upload extensions."""

    _parser_types: ClassVar[dict[str, type[BaseParser]]] = {
        ".pdf": PDFParser,
        ".docx": DocxParser,
        ".md": MarkdownParser,
        ".txt": TextParser,
    }

    @classmethod
    def get_parser(cls, file_path: Path) -> BaseParser:
        """Create a parser selected from a case-insensitive file suffix."""
        path = Path(file_path)
        extension = path.suffix.lower()
        parser_type = cls._parser_types.get(extension)

        if parser_type is None:
            supported_extensions = ", ".join(sorted(cls._parser_types))
            raise UnsupportedFileTypeError(
                f"Unsupported document type for '{path.name}'. "
                f"Supported extensions: {supported_extensions}."
            )

        return parser_type()

    @classmethod
    def parse(cls, file_path: Path) -> ParsedDocument:
        """Select a parser and parse one document."""
        path = Path(file_path)
        return cls.get_parser(path).parse(path)
