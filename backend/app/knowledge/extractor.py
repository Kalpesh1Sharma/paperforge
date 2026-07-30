"""Validation-focused orchestration with deterministic provider fallback."""

import json
import logging
import math
from time import perf_counter
from uuid import UUID

from pydantic import ValidationError

from app.knowledge.exceptions import (
    GroqNetworkError,
    GroqRateLimitError,
    GroqSchemaValidationError,
    GroqTemporaryServiceError,
    GroqTimeoutError,
    InvalidKnowledgeObjectError,
    KnowledgeExtractionError,
    KnowledgeError,
    MalformedGroqJsonError,
    ProviderError,
    RecoverableProviderError,
    UnexpectedGroqResponseError,
)
from app.knowledge.models import KnowledgeExtractionMetadata, KnowledgeObject
from app.knowledge.providers import (
    BaseKnowledgeProvider,
    DeterministicKnowledgeProvider,
)
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
    """Validate primary extraction and use deterministic fallback when safe."""

    def __init__(
        self,
        provider: BaseKnowledgeProvider,
        fallback_provider: BaseKnowledgeProvider | None = None,
    ) -> None:
        """Configure a primary provider and an optional local fallback provider."""
        self._provider = provider
        self._fallback_provider = (
            fallback_provider
            if fallback_provider is not None
            else DeterministicKnowledgeProvider()
        )

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        """Extract and validate knowledge for one source-addressable chunk."""
        self._validate_chunk(chunk)
        started_at = perf_counter()

        try:
            knowledge_object = self._provider.extract(chunk)
            self._validate_knowledge_object(knowledge_object)
            return knowledge_object
        except RecoverableProviderError as exc:
            return self._fallback(
                chunk,
                started_at,
                reason=self._reason_for(exc),
            )
        except TimeoutError:
            return self._fallback(chunk, started_at, reason="timeout")
        except ConnectionError:
            return self._fallback(chunk, started_at, reason="connection")
        except json.JSONDecodeError:
            return self._fallback(chunk, started_at, reason="malformed_response")
        except ValidationError:
            return self._fallback(chunk, started_at, reason="schema_validation")
        except KnowledgeError:
            raise
        except Exception as exc:
            logger.error(
                "Knowledge provider failed | chunk_id=%s | outcome=failure",
                chunk.chunk_id,
            )
            raise ProviderError(
                f"Knowledge provider failed for chunk {chunk.chunk_id}."
            ) from exc

    def _fallback(
        self,
        chunk: DocumentChunk,
        started_at: float,
        *,
        reason: str,
    ) -> KnowledgeObject:
        """Return one validated local fallback result without retrying primary I/O."""
        try:
            fallback_object = self._fallback_provider.extract(chunk)
        except KnowledgeError:
            raise
        except Exception as exc:
            logger.error(
                "Deterministic fallback provider failed | chunk_id=%s | "
                "outcome=failure",
                chunk.chunk_id,
            )
            raise ProviderError(
                f"Deterministic fallback failed for chunk {chunk.chunk_id}."
            ) from exc

        self._validate_knowledge_object(fallback_object)
        fallback_metadata = KnowledgeExtractionMetadata(
            provider="deterministic",
            model=None,
            elapsed_ms=self._elapsed_ms(started_at),
            successful=True,
            fallback=True,
            reason=reason,
        )
        fallback_object = fallback_object.model_copy(
            update={"extraction_metadata": fallback_metadata}
        )
        self._validate_knowledge_object(fallback_object)
        self._log_fallback(chunk, reason, started_at)
        return fallback_object

    @staticmethod
    def _reason_for(error: RecoverableProviderError) -> str:
        """Map only known recoverable failures to safe normalized telemetry."""
        if isinstance(error, GroqRateLimitError):
            return "rate_limit"
        if isinstance(error, GroqTimeoutError):
            return "timeout"
        if isinstance(error, GroqNetworkError):
            return "connection"
        if isinstance(error, GroqTemporaryServiceError):
            return "api_unavailable"
        if isinstance(error, (MalformedGroqJsonError, UnexpectedGroqResponseError)):
            return "malformed_response"
        if isinstance(error, (GroqSchemaValidationError, InvalidKnowledgeObjectError)):
            return "schema_validation"
        return "provider_transient"

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        """Return a finite non-negative elapsed duration for operational metadata."""
        return max(0.0, (perf_counter() - started_at) * 1000)

    @staticmethod
    def _log_fallback(
        chunk: DocumentChunk,
        reason: str,
        started_at: float,
    ) -> None:
        """Log one safe warning once a deterministic fallback is available."""
        logger.warning(
            "Knowledge extraction fallback | provider=groq | fallback=true | "
            "reason=%s | message=Using deterministic knowledge extraction. | "
            "chunk_id=%s | elapsed_ms=%.2f",
            reason,
            chunk.chunk_id,
            KnowledgeExtractor._elapsed_ms(started_at),
        )

    @classmethod
    def _validate_chunk(cls, chunk: object) -> None:
        if not isinstance(chunk, DocumentChunk):
            raise KnowledgeExtractionError("Input must be a DocumentChunk instance.")
        if not isinstance(chunk.chunk_id, UUID):
            raise KnowledgeExtractionError("Chunk chunk_id must be a UUID.")
        if (
            not isinstance(chunk.document_filename, str)
            or not chunk.document_filename.strip()
        ):
            raise KnowledgeExtractionError(
                "Chunk document_filename must be non-empty text."
            )
        if isinstance(chunk.chunk_index, bool) or not isinstance(
            chunk.chunk_index,
            int,
        ):
            raise KnowledgeExtractionError(
                "Chunk chunk_index must be a non-negative integer."
            )
        if chunk.chunk_index < 0:
            raise KnowledgeExtractionError(
                "Chunk chunk_index must be a non-negative integer."
            )
        if not isinstance(chunk.text, str) or not chunk.text.strip():
            raise KnowledgeExtractionError(
                "Chunk text must contain non-whitespace content."
            )

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
        if getattr(knowledge_object, "__pydantic_extra__", None):
            raise InvalidKnowledgeObjectError(
                "KnowledgeObject must not contain extra fields."
            )
        try:
            chunk_id = knowledge_object.chunk_id
        except AttributeError as exc:
            raise InvalidKnowledgeObjectError(
                "KnowledgeObject must include a chunk_id."
            ) from exc
        if not isinstance(chunk_id, UUID):
            raise InvalidKnowledgeObjectError(
                "KnowledgeObject chunk_id must be a UUID."
            )

        for field_name in _KNOWLEDGE_COLLECTION_FIELDS:
            try:
                values = getattr(knowledge_object, field_name)
            except AttributeError as exc:
                raise InvalidKnowledgeObjectError(
                    f"KnowledgeObject must include {field_name}."
                ) from exc
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) for value in values
            ):
                raise InvalidKnowledgeObjectError(
                    f"KnowledgeObject {field_name} must be a tuple of strings."
                )

        try:
            confidence = knowledge_object.confidence
        except AttributeError as exc:
            raise InvalidKnowledgeObjectError(
                "KnowledgeObject must include confidence."
            ) from exc
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, float)
            or not math.isfinite(confidence)
            or not 0.0 <= confidence <= 1.0
        ):
            raise InvalidKnowledgeObjectError(
                "KnowledgeObject confidence must be a finite float from 0 to 1."
            )

        try:
            metadata = knowledge_object.extraction_metadata
        except AttributeError as exc:
            raise InvalidKnowledgeObjectError(
                "KnowledgeObject must include extraction_metadata."
            ) from exc
        if metadata is None:
            return
        if not isinstance(metadata, KnowledgeExtractionMetadata):
            raise InvalidKnowledgeObjectError(
                "KnowledgeObject extraction_metadata must be "
                "KnowledgeExtractionMetadata or None."
            )
        if getattr(metadata, "__pydantic_extra__", None):
            raise InvalidKnowledgeObjectError(
                "KnowledgeObject extraction_metadata must not contain extra fields."
            )
        try:
            KnowledgeExtractionMetadata.model_validate(
                metadata.model_dump(mode="python", warnings="error")
            )
        except (AttributeError, TypeError, ValidationError, ValueError) as exc:
            raise InvalidKnowledgeObjectError(
                "KnowledgeObject extraction_metadata failed structural validation."
            ) from exc

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
