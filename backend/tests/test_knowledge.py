"""Tests for the deterministic knowledge extraction foundation."""

import logging
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.knowledge import (
    BaseKnowledgeProvider,
    InvalidKnowledgeObjectError,
    KnowledgeExtractionError,
    KnowledgeExtractor,
    KnowledgeObject,
    KnowledgePipeline,
    ProviderError,
)
from app.models.document_chunk import DocumentChunk


def _chunk(index: int = 0, text: str = "Research evidence") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=uuid4(),
        document_filename="research.txt",
        chunk_index=index,
        text=text,
        start_char=index * 100,
        end_char=index * 100 + len(text),
        word_count=len(text.split()),
        character_count=len(text),
        metadata={"source_file_type": "txt", "source_metadata": {}},
    )


def _knowledge(chunk_id: UUID, confidence: float = 0.8) -> KnowledgeObject:
    return KnowledgeObject(
        chunk_id=chunk_id,
        entities=("PaperForge",),
        facts=("The evidence is reproducible.",),
        definitions=("Evidence: supporting information.",),
        metrics=("Accuracy: 95%",),
        dates=("2026-07-27",),
        references=("Reference 1",),
        confidence=confidence,
    )


class RecordingProvider(BaseKnowledgeProvider):
    """Deterministic provider used to assert orchestration behavior."""

    def __init__(self, results: dict[UUID, KnowledgeObject]) -> None:
        self.results = results
        self.calls: list[DocumentChunk] = []

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        self.calls.append(chunk)
        return self.results[chunk.chunk_id]


class InvalidResultProvider(BaseKnowledgeProvider):
    """Provider that deliberately violates the runtime return contract."""

    def __init__(self, result: object) -> None:
        self._result = result

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        return self._result  # type: ignore[return-value]


class FailingProvider(BaseKnowledgeProvider):
    """Provider that exercises error wrapping and logging."""

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        raise RuntimeError("provider transport failed")


def test_knowledge_object_is_strict_and_validates_confidence() -> None:
    chunk_id = uuid4()

    with pytest.raises(ValidationError):
        KnowledgeObject(chunk_id=str(chunk_id), confidence=0.5)
    with pytest.raises(ValidationError):
        KnowledgeObject(chunk_id=chunk_id, entities=("valid", 1), confidence=0.5)
    with pytest.raises(ValidationError):
        KnowledgeObject(chunk_id=chunk_id, confidence=0.5, unexpected="value")

    for confidence in (-0.1, 1.1, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            KnowledgeObject(chunk_id=chunk_id, confidence=confidence)


def test_knowledge_object_is_immutable_after_construction() -> None:
    knowledge = _knowledge(uuid4())

    with pytest.raises(ValidationError):
        knowledge.confidence = 0.4
    with pytest.raises(AttributeError):
        knowledge.entities.append("New entity")  # type: ignore[attr-defined]


def test_extractor_invokes_provider_and_preserves_object_identity() -> None:
    chunk = _chunk()
    expected = _knowledge(chunk.chunk_id)
    provider = RecordingProvider({chunk.chunk_id: expected})

    result = KnowledgeExtractor(provider).extract(chunk)

    assert provider.calls == [chunk]
    assert result is expected


def test_extractor_rejects_validation_bypassed_chunk() -> None:
    chunk = DocumentChunk.model_construct(
        chunk_id=uuid4(),
        document_filename="research.txt",
        chunk_index=0,
        text="Research evidence",
        start_char=0,
        end_char=17,
        word_count=2,
        character_count=1,
        metadata={},
    )
    provider = RecordingProvider({})

    with pytest.raises(KnowledgeExtractionError, match="character_count"):
        KnowledgeExtractor(provider).extract(chunk)

    assert provider.calls == []


def test_extractor_rejects_invalid_provider_output() -> None:
    chunk = _chunk()
    corrupted = KnowledgeObject.model_construct(
        chunk_id=chunk.chunk_id,
        entities=["PaperForge"],
        facts=(),
        definitions=(),
        metrics=(),
        dates=(),
        references=(),
        confidence=0.8,
    )

    with pytest.raises(InvalidKnowledgeObjectError, match="entities"):
        KnowledgeExtractor(InvalidResultProvider(corrupted)).extract(chunk)

    with pytest.raises(InvalidKnowledgeObjectError, match="KnowledgeObject"):
        KnowledgeExtractor(InvalidResultProvider({})).extract(chunk)


def test_extractor_wraps_provider_failure_without_logging_chunk_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    chunk = _chunk(text="Sensitive research evidence")

    with caplog.at_level(logging.ERROR, logger="app.knowledge.extractor"):
        with pytest.raises(ProviderError, match=str(chunk.chunk_id)):
            KnowledgeExtractor(FailingProvider()).extract(chunk)

    assert str(chunk.chunk_id) in caplog.text
    assert chunk.text not in caplog.text


def test_pipeline_preserves_order_duplicates_length_and_identity() -> None:
    first_chunk = _chunk(0)
    second_chunk = _chunk(1)
    first_knowledge = _knowledge(first_chunk.chunk_id)
    second_knowledge = _knowledge(second_chunk.chunk_id)
    provider = RecordingProvider(
        {
            first_chunk.chunk_id: first_knowledge,
            second_chunk.chunk_id: second_knowledge,
        }
    )
    pipeline = KnowledgePipeline(KnowledgeExtractor(provider))
    chunks = [first_chunk, first_chunk, second_chunk]

    results = pipeline.process(chunks)

    assert len(results) == len(chunks)
    assert provider.calls == chunks
    assert results == [first_knowledge, first_knowledge, second_knowledge]
    assert results[0] is first_knowledge
    assert results[1] is first_knowledge
    assert results[2] is second_knowledge


def test_pipeline_returns_empty_list_for_empty_input() -> None:
    provider = RecordingProvider({})

    results = KnowledgePipeline(KnowledgeExtractor(provider)).process([])

    assert results == []
    assert provider.calls == []


def test_pipeline_is_deterministic_for_a_deterministic_provider() -> None:
    chunk = _chunk()
    expected = _knowledge(chunk.chunk_id)
    provider = RecordingProvider({chunk.chunk_id: expected})
    pipeline = KnowledgePipeline(KnowledgeExtractor(provider))

    first = pipeline.process([chunk])
    second = pipeline.process([chunk])

    assert first == second
    assert first[0] is expected
    assert second[0] is expected
