"""Base interface for knowledge providers."""

from abc import ABC, abstractmethod

from app.knowledge.models import KnowledgeObject
from app.models.document_chunk import DocumentChunk


class BaseKnowledgeProvider(ABC):
    """Abstract interface implemented by all knowledge providers."""

    @abstractmethod
    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        """Extract structured knowledge from one document chunk."""
        raise NotImplementedError