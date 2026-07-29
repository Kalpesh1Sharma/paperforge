"""Meaningful exceptions raised by the knowledge extraction layer."""


class KnowledgeError(Exception):
    """Base exception raised by the knowledge extraction layer."""


class KnowledgeExtractionError(KnowledgeError):
    """Raised when a chunk cannot be processed for knowledge extraction."""


class ProviderError(KnowledgeExtractionError):
    """Raised when a knowledge provider fails during extraction."""


class InvalidKnowledgeObjectError(KnowledgeExtractionError):
    """Raised when a provider returns an invalid KnowledgeObject."""


class GroqProviderError(ProviderError):
    """Base exception raised by the Groq knowledge provider."""


class GroqConfigurationError(GroqProviderError):
    """Raised when Groq provider configuration is incomplete or invalid."""


class MissingGroqApiKeyError(GroqConfigurationError):
    """Raised when no usable Groq API key is configured."""


class MissingGroqModelError(GroqConfigurationError):
    """Raised when no usable Groq model is configured."""


class GroqAuthenticationError(GroqProviderError):
    """Raised when Groq rejects the configured credentials."""


class GroqRateLimitError(GroqProviderError):
    """Raised when Groq rejects a request because of rate limiting."""


class GroqTimeoutError(GroqProviderError):
    """Raised when a Groq request exceeds the SDK timeout."""


class GroqNetworkError(GroqProviderError):
    """Raised when the Groq service cannot be reached."""


class MalformedGroqJsonError(GroqProviderError):
    """Raised when Groq returns content that is not valid JSON."""


class GroqSchemaValidationError(GroqProviderError):
    """Raised when valid Groq JSON does not match the response schema."""


class UnexpectedGroqResponseError(GroqProviderError):
    """Raised when a Groq completion omits an expected response field."""
