"""Safe exceptions raised by provider-neutral AI transports."""


class CompatibleAIError(RuntimeError):
    """Base exception for an OpenAI-compatible request."""


class CompatibleAIConfigurationError(CompatibleAIError):
    """Raised when a provider configuration is unsafe or incomplete."""


class CompatibleAIAuthenticationError(CompatibleAIError):
    """Raised when a provider rejects its configured credentials."""


class CompatibleAIRateLimitError(CompatibleAIError):
    """Raised after rate-limit retries are exhausted."""


class CompatibleAITimeoutError(CompatibleAIError):
    """Raised after request timeout retries are exhausted."""


class CompatibleAINetworkError(CompatibleAIError):
    """Raised after network retries are exhausted."""


class CompatibleAITemporaryServiceError(CompatibleAIError):
    """Raised after transient server retries are exhausted."""


class CompatibleAIRequestError(CompatibleAIError):
    """Raised when a provider rejects a non-retryable request."""


class CompatibleAIMalformedResponseError(CompatibleAIError):
    """Raised when a provider response omits completion content."""
