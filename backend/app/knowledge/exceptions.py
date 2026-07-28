"""Meaningful exceptions raised by the knowledge extraction layer."""


class KnowledgeError(Exception):
    """Base exception raised by the knowledge extraction layer."""


class KnowledgeExtractionError(KnowledgeError):
    """Raised when a chunk cannot be processed for knowledge extraction."""


class ProviderError(KnowledgeExtractionError):
    """Raised when a knowledge provider fails during extraction."""


class InvalidKnowledgeObjectError(KnowledgeExtractionError):
    """Raised when a provider returns an invalid KnowledgeObject."""
