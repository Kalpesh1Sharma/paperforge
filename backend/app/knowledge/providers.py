"""Provider abstraction for future knowledge extraction integrations."""

from abc import ABC, abstractmethod

from app.knowledge.models import KnowledgeObject
from app.models.document_chunk import DocumentChunk


class BaseKnowledgeProvider(ABC):
    """Produce knowledge objects from deterministic document chunks."""

    @abstractmethod
    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        """Extract knowledge from one chunk without changing the chunk."""
