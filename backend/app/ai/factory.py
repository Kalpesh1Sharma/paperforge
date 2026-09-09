"""Construct coherent collaborators for the configured provider chain."""

import logging
from dataclasses import dataclass

from app.ai.compatible_client import CompatibleChatClient
from app.ai.configuration import ProviderConfiguration, configured_provider_order
from app.ai.gemini_client import GeminiNativeChatClient
from app.config import settings
from app.knowledge.providers import (
    BaseKnowledgeProvider,
    CompatibleKnowledgeProvider,
    DeterministicKnowledgeProvider,
    FailoverKnowledgeProvider,
    GroqKnowledgeProvider,
)
from app.reports.deterministic_document_synthesizer import (
    DeterministicDocumentSynthesizer,
)
from app.reports.document_synthesizer import DocumentSynthesizer
from app.reports.failover_document_synthesizer import FailoverDocumentSynthesizer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderCollaborators:
    """Provider-specific components used by one complete pipeline run."""

    knowledge_provider: BaseKnowledgeProvider
    document_synthesizer: DocumentSynthesizer


def build_provider_collaborators() -> ProviderCollaborators:
    """Build ordered remote provider pairs with a guaranteed local fallback."""
    configurations = configured_provider_order()
    if len(configurations) == 1 and configurations[0].name == "deterministic":
        return ProviderCollaborators(
            knowledge_provider=DeterministicKnowledgeProvider(),
            document_synthesizer=DeterministicDocumentSynthesizer(),
        )

    knowledge_providers: list[tuple[str, BaseKnowledgeProvider]] = []
    document_synthesizers: list[tuple[str, DocumentSynthesizer]] = []
    for configuration in configurations:
        if configuration.name == "deterministic":
            continue
        if not _is_complete(configuration):
            logger.warning(
                "Skipping incomplete AI provider configuration | provider=%s",
                configuration.name,
            )
            continue
        knowledge_provider, document_synthesizer = _build_remote_pair(configuration)
        knowledge_providers.append((configuration.name, knowledge_provider))
        document_synthesizers.append((configuration.name, document_synthesizer))

    return ProviderCollaborators(
        knowledge_provider=FailoverKnowledgeProvider(
            tuple(knowledge_providers), DeterministicKnowledgeProvider()
        ),
        document_synthesizer=FailoverDocumentSynthesizer(
            tuple(document_synthesizers)
        ),
    )


def _build_remote_pair(
    configuration: ProviderConfiguration,
) -> tuple[BaseKnowledgeProvider, DocumentSynthesizer]:
    if configuration.name == "groq":
        return GroqKnowledgeProvider(), DocumentSynthesizer()

    client_class = (
        GeminiNativeChatClient
        if configuration.name == "gemini"
        else CompatibleChatClient
    )
    client = client_class(
        configuration,
        max_retries=settings.ai_max_retries,
        retry_base_seconds=settings.ai_retry_base_seconds,
        timeout_seconds=settings.ai_timeout_seconds,
    )
    return CompatibleKnowledgeProvider(client), DocumentSynthesizer(client)


def _is_complete(configuration: ProviderConfiguration) -> bool:
    if not configuration.api_key or not configuration.model:
        return False
    return configuration.name == "groq" or bool(configuration.base_url)
