"""Document parsing interfaces and concrete parser implementations."""

from app.parsers.base import (
    BaseParser,
    DOCXParsingError,
    DocumentParsingError,
    EmptyDocumentError,
    FileAccessError,
    PDFParsingError,
    TextDecodingError,
    UnsupportedFileTypeError,
)
from app.parsers.docx_parser import DocxParser
from app.parsers.markdown_parser import MarkdownParser
from app.parsers.parser_factory import ParserFactory
from app.parsers.pdf_parser import PDFParser
from app.parsers.text_parser import TextParser

__all__ = [
    "BaseParser",
    "DOCXParsingError",
    "DocxParser",
    "DocumentParsingError",
    "EmptyDocumentError",
    "FileAccessError",
    "MarkdownParser",
    "ParserFactory",
    "PDFParser",
    "PDFParsingError",
    "TextDecodingError",
    "TextParser",
    "UnsupportedFileTypeError",
]
