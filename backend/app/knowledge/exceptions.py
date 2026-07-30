"""Meaningful exceptions raised by the knowledge extraction layer."""


class KnowledgeError(Exception):
    """Base exception raised by the knowledge extraction layer."""


class KnowledgeExtractionError(KnowledgeError):
    """Raised when a chunk cannot be processed for knowledge extraction."""


class ProviderError(KnowledgeExtractionError):
    """Raised when a knowledge provider fails during extraction."""


class RecoverableProviderError(ProviderError):
    """Marker for provider failures safe to handle with local fallback."""


class InvalidKnowledgeObjectError(RecoverableProviderError):
    """Raised when a provider returns an invalid KnowledgeObject."""


class GroqProviderError(ProviderError):
    """Base exception raised by the Groq knowledge provider."""


class RecoverableGroqProviderError(GroqProviderError, RecoverableProviderError):
    """Marker for transient or malformed Groq extraction failures."""


class GroqConfigurationError(GroqProviderError):
    """Raised when Groq provider configuration is incomplete or invalid."""


class MissingGroqApiKeyError(GroqConfigurationError):
    """Raised when no usable Groq API key is configured."""


class MissingGroqModelError(GroqConfigurationError):
    """Raised when no usable Groq model is configured."""


class GroqAuthenticationError(GroqProviderError):
    """Raised when Groq rejects the configured credentials."""


class GroqRateLimitError(RecoverableGroqProviderError):
    """Raised when Groq rejects a request because of rate limiting."""


class GroqTimeoutError(RecoverableGroqProviderError):
    """Raised when a Groq request exceeds the SDK timeout."""


class GroqNetworkError(RecoverableGroqProviderError):
    """Raised when the Groq service cannot be reached."""


class GroqTemporaryServiceError(RecoverableGroqProviderError):
    """Raised when Groq returns a transient 5xx service failure."""


class MalformedGroqJsonError(RecoverableGroqProviderError):
    """Raised when Groq returns content that is not valid JSON."""


class GroqSchemaValidationError(RecoverableGroqProviderError):
    """Raised when valid Groq JSON does not match the response schema."""


class UnexpectedGroqResponseError(RecoverableGroqProviderError):
    """Raised when a Groq completion omits an expected response field."""
