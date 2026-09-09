"""Knowledge extraction through an OpenAI-compatible provider."""

import json
import logging
from time import perf_counter

from pydantic import ValidationError

from app.ai import CompatibleChatClient
from app.ai.exceptions import (
    CompatibleAIAuthenticationError,
    CompatibleAIConfigurationError,
    CompatibleAIMalformedResponseError,
    CompatibleAINetworkError,
    CompatibleAIRateLimitError,
    CompatibleAIRequestError,
    CompatibleAITemporaryServiceError,
    CompatibleAITimeoutError,
)
from app.knowledge.exceptions import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderError,
    ProviderMalformedResponseError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderSchemaValidationError,
    ProviderTemporaryServiceError,
    ProviderTimeoutError,
)
from app.knowledge.models import KnowledgeExtractionMetadata, KnowledgeObject
from app.knowledge.prompts import KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT
from app.knowledge.providers.base import BaseKnowledgeProvider
from app.knowledge.schemas import KnowledgeResponse
from app.models.document_chunk import DocumentChunk

logger = logging.getLogger(__name__)


class CompatibleKnowledgeProvider(BaseKnowledgeProvider):
    """Extract strict knowledge with Gemini, Mistral, or a custom endpoint."""

    def __init__(self, client: CompatibleChatClient) -> None:
        self._client = client

    @property
    def provider_name(self) -> str:
        """Return a non-secret label for fallback telemetry."""
        return self._client.provider

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        started_at = perf_counter()
        try:
            content = self._client.complete(
                [
                    {"role": "system", "content": KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": chunk.text},
                ]
            )
            response = self._parse_response(content)
        except CompatibleAIConfigurationError as exc:
            raise ProviderConfigurationError(str(exc)) from exc
        except CompatibleAIAuthenticationError as exc:
            raise ProviderAuthenticationError(str(exc)) from exc
        except CompatibleAIRateLimitError as exc:
            raise ProviderRateLimitError(str(exc)) from exc
        except CompatibleAITimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except CompatibleAINetworkError as exc:
            raise ProviderNetworkError(str(exc)) from exc
        except CompatibleAITemporaryServiceError as exc:
            raise ProviderTemporaryServiceError(str(exc)) from exc
        except CompatibleAIMalformedResponseError as exc:
            raise ProviderMalformedResponseError(str(exc)) from exc
        except CompatibleAIRequestError as exc:
            raise ProviderError(str(exc)) from exc

        result = KnowledgeObject(
            chunk_id=chunk.chunk_id,
            entities=response.entities,
            facts=response.facts,
            definitions=response.definitions,
            metrics=response.metrics,
            dates=response.dates,
            references=response.references,
            confidence=response.confidence,
            extraction_metadata=KnowledgeExtractionMetadata(
                provider=self._client.provider,
                model=self._client.model,
                elapsed_ms=max(0.0, (perf_counter() - started_at) * 1000),
                successful=True,
            ),
        )
        logger.info(
            "Knowledge extraction succeeded | provider=%s | chunk_id=%s | "
            "model=%s | elapsed_ms=%.2f",
            self._client.provider,
            chunk.chunk_id,
            self._client.model,
            max(0.0, (perf_counter() - started_at) * 1000),
        )
        return result

    @staticmethod
    def _parse_response(content: str) -> KnowledgeResponse:
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderMalformedResponseError(
                "Provider response was not valid JSON."
            ) from exc
        try:
            return KnowledgeResponse.model_validate_json(content)
        except ValidationError as exc:
            raise ProviderSchemaValidationError(
                "Provider response did not match the knowledge response schema."
            ) from exc
