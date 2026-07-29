"""Synchronous Groq-backed knowledge extraction provider."""

import json
import logging
from time import perf_counter

from groq import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    Groq,
    RateLimitError,
)
from pydantic import ValidationError

from app.config import settings
from app.knowledge.exceptions import (
    GroqAuthenticationError,
    GroqNetworkError,
    GroqProviderError,
    GroqRateLimitError,
    GroqSchemaValidationError,
    GroqTimeoutError,
    MalformedGroqJsonError,
    MissingGroqApiKeyError,
    MissingGroqModelError,
    UnexpectedGroqResponseError,
)
from app.knowledge.models import KnowledgeObject
from app.knowledge.prompts import KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT
from app.knowledge.providers.base import BaseKnowledgeProvider
from app.knowledge.schemas import KnowledgeResponse
from app.models.document_chunk import DocumentChunk

logger = logging.getLogger(__name__)


class GroqKnowledgeProvider(BaseKnowledgeProvider):
    """Extract validated knowledge through one synchronous Groq request."""

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        """Request JSON-only knowledge extraction for one document chunk."""
        started_at = perf_counter()
        model = self._configured_model_name()

        try:
            api_key, model = self._configuration()
            client = Groq(api_key=api_key, max_retries=0)
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": chunk.text,
                    },
                ],
                temperature=0,
                stream=False,
                response_format={"type": "json_object"},
            )
            response = self._parse_response(self._completion_content(completion))
            knowledge_object = KnowledgeObject(
                chunk_id=chunk.chunk_id,
                entities=response.entities,
                facts=response.facts,
                definitions=response.definitions,
                metrics=response.metrics,
                dates=response.dates,
                references=response.references,
                confidence=response.confidence,
            )
        except APITimeoutError as exc:
            self._log_failure(chunk, model, started_at)
            raise GroqTimeoutError("Groq request timed out.") from exc
        except AuthenticationError as exc:
            self._log_failure(chunk, model, started_at)
            raise GroqAuthenticationError("Groq authentication failed.") from exc
        except RateLimitError as exc:
            self._log_failure(chunk, model, started_at)
            raise GroqRateLimitError("Groq request was rate limited.") from exc
        except APIConnectionError as exc:
            self._log_failure(chunk, model, started_at)
            raise GroqNetworkError("Groq service could not be reached.") from exc
        except APIError as exc:
            self._log_failure(chunk, model, started_at)
            raise GroqProviderError("Groq request failed.") from exc
        except GroqProviderError:
            self._log_failure(chunk, model, started_at)
            raise
        except Exception as exc:
            self._log_failure(chunk, model, started_at)
            raise GroqProviderError("Groq knowledge extraction failed.") from exc

        self._log_success(chunk, model, started_at)
        return knowledge_object

    @staticmethod
    def _configuration() -> tuple[str, str]:
        api_key = settings.groq_api_key
        if not isinstance(api_key, str) or not api_key.strip():
            raise MissingGroqApiKeyError("GROQ_API_KEY must be configured.")

        model = settings.groq_model
        if not isinstance(model, str) or not model.strip():
            raise MissingGroqModelError("GROQ_MODEL must be configured.")

        return api_key.strip(), model.strip()

    @staticmethod
    def _configured_model_name() -> str:
        """Return a safe model label for configuration-failure logs."""
        model = settings.groq_model
        if isinstance(model, str) and model.strip():
            return model.strip()
        return "<unconfigured>"

    @staticmethod
    def _completion_content(completion: object) -> str:
        choices = getattr(completion, "choices", None)
        if not isinstance(choices, (list, tuple)) or not choices:
            raise UnexpectedGroqResponseError("Groq response contained no choices.")

        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise UnexpectedGroqResponseError(
                "Groq response contained no usable message content."
            )

        return content

    @staticmethod
    def _parse_response(content: str) -> KnowledgeResponse:
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise MalformedGroqJsonError("Groq response was not valid JSON.") from exc

        try:
            return KnowledgeResponse.model_validate_json(content)
        except ValidationError as exc:
            raise GroqSchemaValidationError(
                "Groq response did not match the knowledge response schema."
            ) from exc

    @staticmethod
    def _log_success(
        chunk: DocumentChunk,
        model: str,
        started_at: float,
    ) -> None:
        logger.info(
            "Groq knowledge extraction succeeded | chunk_id=%s | model=%s | "
            "elapsed_ms=%.2f",
            chunk.chunk_id,
            model,
            (perf_counter() - started_at) * 1000,
        )

    @staticmethod
    def _log_failure(
        chunk: DocumentChunk,
        model: str,
        started_at: float,
    ) -> None:
        logger.error(
            "Groq knowledge extraction failed | chunk_id=%s | model=%s | "
            "elapsed_ms=%.2f",
            chunk.chunk_id,
            model,
            (perf_counter() - started_at) * 1000,
        )
