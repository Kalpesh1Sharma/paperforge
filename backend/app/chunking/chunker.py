"""Orchestrator that validates parsed documents and materializes chunks."""

from typing import Iterable
from uuid import UUID, uuid5

from app.chunking.exceptions import (
    ChunkingInvariantError,
    EmptyDocumentError,
    InvalidParsedDocumentError,
)
from app.chunking.strategy import (
    ChunkSpan,
    ChunkingConfig,
    ChunkingStrategy,
    ParagraphAwareChunkingStrategy,
)
from app.chunking.utils import count_words_and_content, document_fingerprint, is_valid_metadata
from app.models.document_chunk import DocumentChunk
from app.models.parsed_document import ParsedDocument

CHUNK_ID_NAMESPACE = UUID("9d88b7ba-292c-52a3-92d8-2140592f8be9")


class DocumentChunker:
    """Create deterministic DocumentChunk objects from ParsedDocument input."""

    def __init__(self, strategy: ChunkingStrategy | None = None) -> None:
        self._strategy = strategy or ParagraphAwareChunkingStrategy()

    def chunk(
        self,
        document: ParsedDocument,
        config: ChunkingConfig | None = None,
    ) -> list[DocumentChunk]:
        """Validate one document, plan spans, and materialize chunk models."""
        active_config = config or ChunkingConfig()
        self._validate_document(document)
        spans = tuple(self._strategy.plan_spans(document.extracted_text, active_config))
        self._validate_spans(spans, document.extracted_text, active_config)

        fingerprint = document_fingerprint(
            document.filename,
            document.file_type,
            document.extracted_text,
        )
        chunks: list[DocumentChunk] = []
        for chunk_index, span in enumerate(spans):
            text = document.extracted_text[span.start_char : span.end_char]
            word_count, _ = count_words_and_content(text)
            chunk_id = uuid5(
                CHUNK_ID_NAMESPACE,
                f"{fingerprint}\x1f{span.start_char}\x1f{span.end_char}",
            )
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    document_filename=document.filename,
                    chunk_index=chunk_index,
                    text=text,
                    start_char=span.start_char,
                    end_char=span.end_char,
                    word_count=word_count,
                    character_count=len(text),
                    metadata={
                        "source_file_type": document.file_type,
                        "source_metadata": dict(document.metadata),
                    },
                )
            )

        return chunks

    @staticmethod
    def _validate_document(document: object) -> None:
        if not isinstance(document, ParsedDocument):
            raise InvalidParsedDocumentError("Input must be a ParsedDocument instance.")
        if not isinstance(document.filename, str) or not document.filename.strip():
            raise InvalidParsedDocumentError("Document filename must be non-empty text.")
        if not isinstance(document.extracted_text, str):
            raise InvalidParsedDocumentError("Document extracted_text must be text.")
        if document.file_type not in {"pdf", "docx", "md", "txt"}:
            raise InvalidParsedDocumentError("Document file_type is not supported.")
        if document.page_count is not None and (
            isinstance(document.page_count, bool)
            or not isinstance(document.page_count, int)
            or document.page_count < 0
        ):
            raise InvalidParsedDocumentError("Document page_count is invalid.")
        if isinstance(document.word_count, bool) or not isinstance(
            document.word_count,
            int,
        ):
            raise InvalidParsedDocumentError("Document word_count is invalid.")
        if isinstance(document.character_count, bool) or not isinstance(
            document.character_count,
            int,
        ):
            raise InvalidParsedDocumentError("Document character_count is invalid.")
        if not is_valid_metadata(document.metadata):
            raise InvalidParsedDocumentError("Document metadata is not JSON-safe.")

        word_count, has_content = count_words_and_content(document.extracted_text)
        if not has_content:
            raise EmptyDocumentError("Document contains no non-whitespace text.")
        if document.character_count != len(document.extracted_text):
            raise InvalidParsedDocumentError(
                "Document character_count does not match extracted_text."
            )
        if document.word_count != word_count:
            raise InvalidParsedDocumentError(
                "Document word_count does not match extracted_text."
            )

    @staticmethod
    def _validate_spans(
        spans: Iterable[ChunkSpan],
        text: str,
        config: ChunkingConfig,
    ) -> None:
        span_list = tuple(spans)
        if not span_list:
            raise ChunkingInvariantError("Strategy returned no chunk spans.")
        if span_list[0].start_char != 0:
            raise ChunkingInvariantError("The first chunk span must start at zero.")
        if span_list[-1].end_char != len(text):
            raise ChunkingInvariantError("The final chunk span must cover document end.")

        previous: ChunkSpan | None = None
        final_index = len(span_list) - 1
        for index, span in enumerate(span_list):
            if span.start_char < 0 or span.end_char > len(text):
                raise ChunkingInvariantError("Strategy returned an out-of-range span.")
            if span.start_char >= span.end_char:
                raise ChunkingInvariantError("Strategy returned an empty chunk span.")
            character_count = span.end_char - span.start_char
            if index < final_index and character_count > config.max_chars:
                raise ChunkingInvariantError(
                    "A non-final chunk exceeds the configured maximum size."
                )
            if (
                index == final_index
                and character_count
                > config.max_chars + config.effective_min_chunk_chars
            ):
                raise ChunkingInvariantError(
                    "The final chunk exceeds the permitted trailing-tail limit."
                )
            if previous is not None:
                if span.start_char <= previous.start_char:
                    raise ChunkingInvariantError(
                        "Strategy returned non-progressing chunk spans."
                    )
                if span.start_char > previous.end_char:
                    raise ChunkingInvariantError("Strategy returned a gap between spans.")
                if span.end_char <= previous.end_char:
                    raise ChunkingInvariantError(
                        "Strategy returned a duplicate-only chunk span."
                    )
                if (
                    span.end_char - previous.end_char
                    < config.effective_min_chunk_chars
                ):
                    raise ChunkingInvariantError(
                        "Strategy returned a chunk with insufficient new content."
                    )
            previous = span
