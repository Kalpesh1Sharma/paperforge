"""Deterministic, standalone document chunking primitives."""

from app.chunking.chunker import DocumentChunker
from app.chunking.exceptions import (
    ChunkingError,
    ChunkingInvariantError,
    EmptyDocumentError,
    InvalidChunkingConfigError,
    InvalidParsedDocumentError,
)
from app.chunking.strategy import (
    ChunkSpan,
    ChunkingConfig,
    ChunkingStrategy,
    ParagraphAwareChunkingStrategy,
)

__all__ = [
    "ChunkingConfig",
    "ChunkingError",
    "ChunkingInvariantError",
    "ChunkSpan",
    "ChunkingStrategy",
    "DocumentChunker",
    "EmptyDocumentError",
    "InvalidChunkingConfigError",
    "InvalidParsedDocumentError",
    "ParagraphAwareChunkingStrategy",
]
