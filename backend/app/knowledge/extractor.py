"""Validation-focused orchestration for a knowledge provider."""

import logging
import math
from uuid import UUID

from app.knowledge.exceptions import (
    InvalidKnowledgeObjectError,
    KnowledgeExtractionError,
    KnowledgeError,
    ProviderError,
)
from app.knowledge.models import KnowledgeObject
from app.knowledge.providers import BaseKnowledgeProvider
from app.models.document_chunk import DocumentChunk

logger = logging.getLogger(__name__)

_KNOWLEDGE_COLLECTION_FIELDS = (
    "entities",
    "facts",
    "definitions",
    "metrics",
    "dates",
    "references",
)


class KnowledgeExtractor:
    """Validate chunks and provider output while preserving object identity."""

    def __init__(self, provider: BaseKnowledgeProvider) -> None:
        self._provider = provider

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        """Extract and validate knowledge for one source-addressable chunk."""
        self._validate_chunk(chunk)

        try:
            knowledge_object = self._provider.extract(chunk)
        except KnowledgeError:
            raise
        except Exception as exc:
            logger.exception(
                "Knowledge provider failed for chunk_id=%s.",
                chunk.chunk_id,
            )
            raise ProviderError(
                f"Knowledge provider failed for chunk {chunk.chunk_id}."
            ) from exc

        self._validate_knowledge_object(knowledge_object)
        return knowledge_object

    @classmethod
    def _validate_chunk(cls, chunk: object) -> None:
        if not isinstance(chunk, DocumentChunk):
            raise KnowledgeExtractionError("Input must be a DocumentChunk instance.")
        if not isinstance(chunk.chunk_id, UUID):
            raise KnowledgeExtractionError("Chunk chunk_id must be a UUID.")
        if not isinstance(chunk.document_filename, str) or not chunk.document_filename.strip():
            raise KnowledgeExtractionError("Chunk document_filename must be non-empty text.")
        if isinstance(chunk.chunk_index, bool) or not isinstance(chunk.chunk_index, int):
            raise KnowledgeExtractionError("Chunk chunk_index must be a non-negative integer.")
        if chunk.chunk_index < 0:
            raise KnowledgeExtractionError("Chunk chunk_index must be a non-negative integer.")
        if not isinstance(chunk.text, str) or not chunk.text.strip():
            raise KnowledgeExtractionError("Chunk text must contain non-whitespace content.")

        integer_fields = (
            ("start_char", chunk.start_char),
            ("end_char", chunk.end_char),
            ("word_count", chunk.word_count),
            ("character_count", chunk.character_count),
        )
        for field_name, value in integer_fields:
            if isinstance(value, bool) or not isinstance(value, int):
                raise KnowledgeExtractionError(
                    f"Chunk {field_name} must be an integer."
                )

        if chunk.start_char < 0 or chunk.end_char <= chunk.start_char:
            raise KnowledgeExtractionError("Chunk character offsets are invalid.")
        if chunk.end_char - chunk.start_char != len(chunk.text):
            raise KnowledgeExtractionError("Chunk offsets do not match text length.")
        if chunk.character_count != len(chunk.text):
            raise KnowledgeExtractionError(
                "Chunk character_count does not match text length."
            )
        if chunk.word_count != cls._count_words(chunk.text):
            raise KnowledgeExtractionError("Chunk word_count does not match text.")
        if not cls._is_valid_metadata(chunk.metadata):
            raise KnowledgeExtractionError("Chunk metadata is not JSON-safe.")

    @staticmethod
    def _validate_knowledge_object(knowledge_object: object) -> None:
        if not isinstance(knowledge_object, KnowledgeObject):
            raise InvalidKnowledgeObjectError(
                "Provider must return a KnowledgeObject instance."
            )
        if not isinstance(knowledge_object.chunk_id, UUID):
            raise InvalidKnowledgeObjectError("KnowledgeObject chunk_id must be a UUID.")

        for field_name in _KNOWLEDGE_COLLECTION_FIELDS:
            values = getattr(knowledge_object, field_name)
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) for value in values
            ):
                raise InvalidKnowledgeObjectError(
                    f"KnowledgeObject {field_name} must be a tuple of strings."
                )

        confidence = knowledge_object.confidence
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, float)
            or not math.isfinite(confidence)
            or not 0.0 <= confidence <= 1.0
        ):
            raise InvalidKnowledgeObjectError(
                "KnowledgeObject confidence must be a finite float from 0 to 1."
            )

    @staticmethod
    def _count_words(text: str) -> int:
        """Count whitespace-delimited words without allocating a split list."""
        word_count = 0
        in_word = False

        for character in text:
            if character.isspace():
                in_word = False
            elif not in_word:
                word_count += 1
                in_word = True

        return word_count

    @classmethod
    def _is_valid_metadata(cls, metadata: object, *, allow_nested: bool = True) -> bool:
        if not isinstance(metadata, dict):
            return False

        for key, value in metadata.items():
            if not isinstance(key, str):
                return False
            if isinstance(value, float) and not math.isfinite(value):
                return False
            if isinstance(value, (str, int, float, bool, type(None))):
                continue
            if allow_nested and isinstance(value, dict):
                if cls._is_valid_metadata(value, allow_nested=False):
                    continue
            return False

        return True
