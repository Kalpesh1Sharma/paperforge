"""Base interface and shared behavior for document parsers."""

from abc import ABC, abstractmethod
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Mapping

from app.models.parsed_document import FileType, MetadataValue, ParsedDocument

TEXT_BUFFER_MAX_SIZE_BYTES = 1024 * 1024


class DocumentParsingError(Exception):
    """Base exception raised when a document cannot be parsed."""


class UnsupportedFileTypeError(DocumentParsingError):
    """Raised when no parser supports a file extension."""


class FileAccessError(DocumentParsingError):
    """Raised when a document path cannot be safely accessed."""


class EmptyDocumentError(DocumentParsingError):
    """Raised when a document has no extractable non-whitespace text."""


class PDFParsingError(DocumentParsingError):
    """Raised when a PDF is corrupt, encrypted, or otherwise unreadable."""


class DOCXParsingError(DocumentParsingError):
    """Raised when a DOCX file is corrupt or otherwise unreadable."""


class TextDecodingError(DocumentParsingError):
    """Raised when a text-based document is not valid UTF-8."""


class BaseParser(ABC):
    """Contract implemented by every supported document parser."""

    file_type: FileType

    @abstractmethod
    def parse(self, file_path: Path) -> ParsedDocument:
        """Extract one document into the shared ParsedDocument model."""

    def _validate_file_path(self, file_path: Path) -> Path:
        """Ensure a non-empty regular file can be parsed."""
        path = Path(file_path)

        try:
            if not path.exists():
                raise FileAccessError(f"Document does not exist: '{path}'.")
            if not path.is_file():
                raise FileAccessError(f"Document path is not a file: '{path}'.")
            if path.stat().st_size == 0:
                raise EmptyDocumentError(f"Document is empty: '{path.name}'.")
        except OSError as exc:
            raise FileAccessError(f"Unable to access document: '{path}'.") from exc

        return path

    def _create_text_buffer(self) -> SpooledTemporaryFile[str]:
        """Create a bounded-memory buffer for incrementally extracted text."""
        return SpooledTemporaryFile(
            max_size=TEXT_BUFFER_MAX_SIZE_BYTES,
            mode="w+t",
            encoding="utf-8",
            newline="",
        )

    def _build_document(
        self,
        *,
        file_path: Path,
        extracted_text: str,
        page_count: int | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> ParsedDocument:
        """Validate extracted text and build a result without split() copies."""
        word_count = 0
        in_word = False
        has_non_whitespace_text = False

        for character in extracted_text:
            if character.isspace():
                in_word = False
                continue

            has_non_whitespace_text = True
            if not in_word:
                word_count += 1
                in_word = True

        if not has_non_whitespace_text:
            raise EmptyDocumentError(
                f"Document contains no extractable text: '{file_path.name}'."
            )

        return ParsedDocument(
            filename=file_path.name,
            file_type=self.file_type,
            extracted_text=extracted_text,
            page_count=page_count,
            word_count=word_count,
            character_count=len(extracted_text),
            metadata=dict(metadata or {}),
        )
