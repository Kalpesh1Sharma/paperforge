"""Ordered provider failover with a guaranteed local final provider."""

import logging
from time import perf_counter

from app.knowledge.exceptions import ProviderError
from app.knowledge.models import KnowledgeExtractionMetadata, KnowledgeObject
from app.knowledge.providers.base import BaseKnowledgeProvider
from app.models.document_chunk import DocumentChunk

logger = logging.getLogger(__name__)


class FailoverKnowledgeProvider(BaseKnowledgeProvider):
    """Try configured remote providers in order, then extract locally."""

    def __init__(
        self,
        providers: tuple[tuple[str, BaseKnowledgeProvider], ...],
        fallback_provider: BaseKnowledgeProvider,
    ) -> None:
        self._providers = providers
        self._fallback_provider = fallback_provider

    @property
    def provider_name(self) -> str:
        return "ordered_failover"

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        started_at = perf_counter()
        for index, (name, provider) in enumerate(self._providers):
            try:
                return provider.extract(chunk)
            except ProviderError as exc:
                next_name = (
                    self._providers[index + 1][0]
                    if index + 1 < len(self._providers)
                    else "deterministic"
                )
                logger.warning(
                    "Knowledge provider failover | from_provider=%s | "
                    "to_provider=%s | reason=%s | chunk_id=%s",
                    name,
                    next_name,
                    _safe_reason(exc),
                    chunk.chunk_id,
                )

        result = self._fallback_provider.extract(chunk)
        reason = "providers_exhausted" if self._providers else "no_provider_configured"
        return result.model_copy(
            update={
                "extraction_metadata": KnowledgeExtractionMetadata(
                    provider="deterministic",
                    model=None,
                    elapsed_ms=max(0.0, (perf_counter() - started_at) * 1000),
                    successful=True,
                    fallback=True,
                    reason=reason,
                )
            }
        )


def _safe_reason(error: ProviderError) -> str:
    """Return a non-secret, stable error category for operational logs."""
    name = type(error).__name__.casefold()
    for token, reason in (
        ("authentication", "authentication"),
        ("configuration", "configuration"),
        ("ratelimit", "rate_limit"),
        ("timeout", "timeout"),
        ("network", "connection"),
        ("temporary", "api_unavailable"),
        ("malformed", "malformed_response"),
        ("schema", "schema_validation"),
    ):
        if token in name:
            return reason
    return "request_rejected"
