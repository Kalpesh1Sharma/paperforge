"""Ordered, synchronous pipeline for knowledge extraction."""

from app.knowledge.extractor import KnowledgeExtractor
from app.knowledge.models import KnowledgeObject
from app.models.document_chunk import DocumentChunk


class KnowledgePipeline:
    """Extract knowledge from chunks without reordering or transforming results."""

    def __init__(self, extractor: KnowledgeExtractor) -> None:
        self._extractor = extractor

    def process(self, chunks: list[DocumentChunk]) -> list[KnowledgeObject]:
        """Extract one KnowledgeObject for each input chunk in source order."""
        knowledge_objects: list[KnowledgeObject] = []
        for chunk in chunks:
            knowledge_objects.append(self._extractor.extract(chunk))

        return knowledge_objects
