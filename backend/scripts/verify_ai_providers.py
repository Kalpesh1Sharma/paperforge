"""Run a small, source-free live contract check for configured AI providers."""

from __future__ import annotations

import argparse
import sys
from uuid import uuid4

from app.ai.compatible_client import CompatibleChatClient
from app.ai.configuration import (
    SUPPORTED_PROVIDERS,
    ProviderConfiguration,
    configured_provider,
)
from app.ai.gemini_client import GeminiNativeChatClient
from app.config import settings
from app.knowledge.exceptions import KnowledgeError
from app.knowledge.providers import (
    BaseKnowledgeProvider,
    CompatibleKnowledgeProvider,
    GroqKnowledgeProvider,
)
from app.models.document_chunk import DocumentChunk

REMOTE_PROVIDERS = ("gemini", "mistral", "groq", "openai_compatible")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify configured PaperForge AI providers without real sources."
    )
    parser.add_argument(
        "providers",
        nargs="*",
        default=list(REMOTE_PROVIDERS),
        help="Providers to verify (default: every configured remote provider).",
    )
    arguments = parser.parse_args()
    requested = tuple(name.casefold() for name in arguments.providers)
    invalid = tuple(name for name in requested if name not in SUPPORTED_PROVIDERS)
    if invalid or "deterministic" in requested:
        parser.error("Choose from: gemini, mistral, groq, openai_compatible")

    failures = 0
    for name in requested:
        configuration = configured_provider(name)
        if not _is_complete(configuration):
            print(f"SKIP {name}: configuration is incomplete")
            continue
        try:
            result = _provider(name, configuration).extract(_verification_chunk())
        except KnowledgeError as exc:
            failures += 1
            print(f"FAIL {name}: {type(exc).__name__}")
            continue
        metadata = result.extraction_metadata
        model = metadata.model if metadata is not None else configuration.model
        print(f"PASS {name}: model={model}")
    return 1 if failures else 0


def _provider(
    name: str,
    configuration: ProviderConfiguration,
) -> BaseKnowledgeProvider:
    if name == "groq":
        return GroqKnowledgeProvider()
    client_class = (
        GeminiNativeChatClient if name == "gemini" else CompatibleChatClient
    )
    client = client_class(
        configuration,
        max_retries=settings.ai_max_retries,
        retry_base_seconds=settings.ai_retry_base_seconds,
        timeout_seconds=settings.ai_timeout_seconds,
    )
    return CompatibleKnowledgeProvider(client)


def _is_complete(configuration: ProviderConfiguration) -> bool:
    if not configuration.api_key or not configuration.model:
        return False
    return configuration.name == "groq" or bool(configuration.base_url)


def _verification_chunk() -> DocumentChunk:
    text = "PaperForge verifies structured, source-grounded research extraction."
    return DocumentChunk(
        chunk_id=uuid4(),
        document_filename="paperforge-provider-check.txt",
        chunk_index=0,
        text=text,
        start_char=0,
        end_char=len(text),
        word_count=len(text.split()),
        character_count=len(text),
        metadata={"verification": True},
    )


if __name__ == "__main__":
    sys.exit(main())
