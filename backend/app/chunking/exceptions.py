"""Meaningful exceptions raised by the document chunking layer."""


class ChunkingError(Exception):
    """Base exception raised when a document cannot be chunked."""


class InvalidChunkingConfigError(ChunkingError):
    """Raised when chunk-size or overlap configuration is invalid."""


class EmptyDocumentError(ChunkingError):
    """Raised when a document contains no non-whitespace text."""


class InvalidParsedDocumentError(ChunkingError):
    """Raised when ParsedDocument fields fail chunking invariants."""


class ChunkingInvariantError(ChunkingError):
    """Raised when a strategy produces invalid or non-progressing spans."""
