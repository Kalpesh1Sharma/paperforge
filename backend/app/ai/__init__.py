"""Provider-neutral AI configuration and OpenAI-compatible transport."""

from app.ai.compatible_client import CompatibleChatClient
from app.ai.configuration import ProviderConfiguration, configured_provider
from app.ai.gemini_client import GeminiNativeChatClient

__all__ = [
    "CompatibleChatClient",
    "ProviderConfiguration",
    "GeminiNativeChatClient",
    "configured_provider",
]
