"""Regression tests for graceful deterministic knowledge-extraction fallback."""

from copy import deepcopy
import logging
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.knowledge import (
    BaseKnowledgeProvider,
    DeterministicKnowledgeProvider,
    GroqAuthenticationError,
    GroqNetworkError,
    GroqProviderError,
    GroqRateLimitError,
    GroqSchemaValidationError,
    GroqTemporaryServiceError,
    GroqTimeoutError,
    KnowledgeExtractionError,
    KnowledgeExtractionMetadata,
    KnowledgeExtractor,
    KnowledgeObject,
    KnowledgePipeline,
    MalformedGroqJsonError,
    MissingGroqApiKeyError,
    ProviderError,
    UnexpectedGroqResponseError,
)
from app.models.document_chunk import DocumentChunk
from app.reports import ResearchSynthesizer


def _chunk(
    index: int = 0,
    text: str = "NASA improved latency by 95%.",
) -> DocumentChunk:
    """Build a valid deterministic source chunk for extraction tests."""
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


def _knowledge(chunk: DocumentChunk, confidence: float = 0.8) -> KnowledgeObject:
    """Build a primary-provider object with no fallback metadata."""
    return KnowledgeObject(
        chunk_id=chunk.chunk_id,
        entities=("PaperForge",),
        facts=("PaperForge preserves source-backed evidence.",),
        definitions=("Evidence means source-backed information.",),
        metrics=("95%",),
        dates=("2026-07-30",),
        references=("https://example.com/source",),
        confidence=confidence,
    )


class RaisingProvider(BaseKnowledgeProvider):
    """Provider double that reports one controlled primary failure."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[DocumentChunk] = []

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        self.calls.append(chunk)
        raise self.error


class InvalidResultProvider(BaseKnowledgeProvider):
    """Provider double that deliberately bypasses the Pydantic result contract."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[DocumentChunk] = []

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        self.calls.append(chunk)
        return self.result  # type: ignore[return-value]


class RecordingDeterministicProvider(DeterministicKnowledgeProvider):
    """Fallback test double that records calls while reusing local extraction."""

    def __init__(self) -> None:
        self.calls: list[DocumentChunk] = []

    def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
        self.calls.append(chunk)
        return super().extract(chunk)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (GroqRateLimitError("rate limited"), "rate_limit"),
        (GroqTimeoutError("timed out"), "timeout"),
        (GroqNetworkError("unreachable"), "connection"),
        (GroqTemporaryServiceError("server error"), "api_unavailable"),
        (MalformedGroqJsonError("bad JSON"), "malformed_response"),
        (UnexpectedGroqResponseError("no completion"), "malformed_response"),
        (GroqSchemaValidationError("bad schema"), "schema_validation"),
        (TimeoutError("transport timeout"), "timeout"),
        (ConnectionError("transport connection"), "connection"),
    ],
)
def test_extractor_uses_one_deterministic_fallback_for_recoverable_failures(
    error: Exception,
    reason: str,
) -> None:
    """Every classified temporary provider failure has one local recovery path."""
    chunk = _chunk()
    before = deepcopy(chunk.model_dump(mode="python"))
    primary = RaisingProvider(error)
    fallback = RecordingDeterministicProvider()

    result = KnowledgeExtractor(primary, fallback).extract(chunk)

    assert primary.calls == [chunk]
    assert fallback.calls == [chunk]
    assert result.chunk_id == chunk.chunk_id
    assert result.extraction_metadata is not None
    assert result.extraction_metadata.provider == "deterministic"
    assert result.extraction_metadata.model is None
    assert result.extraction_metadata.successful is True
    assert result.extraction_metadata.fallback is True
    assert result.extraction_metadata.reason == reason
    assert result.extraction_metadata.elapsed_ms >= 0.0
    assert "extraction_metadata" not in result.model_dump(mode="python")
    assert chunk.model_dump(mode="python") == before


def test_invalid_primary_result_falls_back_with_schema_reason() -> None:
    """A validation-bypassed primary object is treated as malformed output."""
    chunk = _chunk()
    corrupted = KnowledgeObject.model_construct(
        chunk_id=chunk.chunk_id,
        entities=["NASA"],
        facts=(),
        definitions=(),
        metrics=(),
        dates=(),
        references=(),
        confidence=0.8,
    )
    primary = InvalidResultProvider(corrupted)
    fallback = RecordingDeterministicProvider()

    result = KnowledgeExtractor(primary, fallback).extract(chunk)

    assert primary.calls == [chunk]
    assert fallback.calls == [chunk]
    assert result.extraction_metadata is not None
    assert result.extraction_metadata.reason == "schema_validation"


def test_fallback_warning_is_structured_once_and_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fallback telemetry never includes source text or provider exception text."""
    chunk = _chunk(text="Sensitive source evidence with private details.")
    primary = RaisingProvider(GroqRateLimitError("credential=secret; payload=private"))

    with caplog.at_level(logging.WARNING, logger="app.knowledge.extractor"):
        KnowledgeExtractor(primary).extract(chunk)

    warnings = [
        record
        for record in caplog.records
        if record.name == "app.knowledge.extractor"
        and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "provider=groq" in message
    assert "fallback=true" in message
    assert "reason=rate_limit" in message
    assert "Using deterministic knowledge extraction." in message
    assert str(chunk.chunk_id) in message
    assert chunk.text not in message
    assert "credential=secret" not in message
    assert "payload=private" not in message


@pytest.mark.parametrize(
    "error",
    [
        GroqAuthenticationError("invalid credential"),
        MissingGroqApiKeyError("missing configuration"),
        GroqProviderError("permission denied"),
        ProviderError("permanent provider failure"),
    ],
)
def test_nonrecoverable_provider_errors_do_not_invoke_fallback(
    error: Exception,
) -> None:
    """Configuration, permission, and generic failures remain observable."""
    chunk = _chunk()
    primary = RaisingProvider(error)
    fallback = RecordingDeterministicProvider()

    with pytest.raises(type(error)):
        KnowledgeExtractor(primary, fallback).extract(chunk)

    assert primary.calls == [chunk]
    assert fallback.calls == []


def test_programming_error_does_not_use_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected implementation failures retain the existing ProviderError boundary."""
    chunk = _chunk()
    primary = RaisingProvider(RuntimeError("implementation failure"))
    fallback = RecordingDeterministicProvider()

    with caplog.at_level(logging.ERROR, logger="app.knowledge.extractor"):
        with pytest.raises(ProviderError, match=str(chunk.chunk_id)):
            KnowledgeExtractor(primary, fallback).extract(chunk)

    assert fallback.calls == []
    assert "implementation failure" not in caplog.text


def test_invalid_chunk_never_reaches_primary_or_fallback() -> None:
    """Chunk validation precedes all provider work."""
    chunk = DocumentChunk.model_construct(
        chunk_id=uuid4(),
        document_filename="research.txt",
        chunk_index=0,
        text="invalid source",
        start_char=0,
        end_char=14,
        word_count=2,
        character_count=1,
        metadata={},
    )
    primary = RaisingProvider(GroqRateLimitError("rate limited"))
    fallback = RecordingDeterministicProvider()

    with pytest.raises(KnowledgeExtractionError, match="character_count"):
        KnowledgeExtractor(primary, fallback).extract(chunk)

    assert primary.calls == []
    assert fallback.calls == []


def test_fallback_provider_failure_is_not_retried_or_masked() -> None:
    """A broken fallback provider never causes another fallback attempt."""
    chunk = _chunk()
    primary = RaisingProvider(GroqRateLimitError("rate limited"))
    fallback = RaisingProvider(RuntimeError("fallback implementation failure"))

    with pytest.raises(ProviderError, match="Deterministic fallback"):
        KnowledgeExtractor(primary, fallback).extract(chunk)

    assert primary.calls == [chunk]
    assert fallback.calls == [chunk]


def test_deterministic_provider_is_immutable_deduplicated_and_source_backed() -> None:
    """The local provider preserves only recognizable source material."""
    chunk = _chunk(
        text=(
            "NASA released API notes in 2026. NASA released API notes in 2026. "
            "Read [source](https://example.com/notes) and "
            "[source](https://example.com/notes)."
        )
    )
    provider = DeterministicKnowledgeProvider()

    first = provider.extract(chunk)
    second = provider.extract(chunk)

    assert first == second
    assert first.chunk_id == chunk.chunk_id
    assert first.entities == ("NASA", "API")
    assert first.references == ("[source](https://example.com/notes)",)
    assert len(first.entities) == len(set(first.entities))
    assert len(first.references) == len(set(first.references))
    assert 0.45 <= first.confidence <= 0.70
    assert first.extraction_metadata is None
    with pytest.raises(ValidationError):
        first.confidence = 0.9


def test_deterministic_provider_does_not_fabricate_facts() -> None:
    """Unrecognized signal-free text produces valid empty categories."""
    knowledge = DeterministicKnowledgeProvider().extract(
        _chunk(text="lowercase tokens without ending punctuation")
    )

    assert knowledge.entities == ()
    assert knowledge.facts == ()
    assert knowledge.definitions == ()
    assert knowledge.metrics == ()
    assert knowledge.dates == ()
    assert knowledge.references == ()
    assert knowledge.confidence == 0.45


def test_pipeline_and_deterministic_report_synthesis_accept_fallback_objects() -> None:
    """Downstream layers remain unaware of the selected extraction provider."""
    first_chunk = _chunk(0, "PaperForge preserves evidence.")
    second_chunk = _chunk(1, "NASA improved latency by 95%.")
    primary_result = _knowledge(first_chunk)

    class MixedProvider(BaseKnowledgeProvider):
        def __init__(self) -> None:
            self.calls: list[DocumentChunk] = []

        def extract(self, chunk: DocumentChunk) -> KnowledgeObject:
            self.calls.append(chunk)
            if chunk.chunk_id == first_chunk.chunk_id:
                return primary_result
            raise GroqRateLimitError("rate limited")

    primary = MixedProvider()
    results = KnowledgePipeline(KnowledgeExtractor(primary)).process(
        [first_chunk, second_chunk]
    )

    assert len(results) == 2
    assert results[0] is primary_result
    assert results[1].extraction_metadata is not None
    assert results[1].extraction_metadata.fallback is True
    report = ResearchSynthesizer().synthesize(tuple(results))
    assert report.findings


def test_extraction_metadata_is_strict_frozen_and_excluded_from_default_dump() -> None:
    """Operational metadata is visible on the model but absent from AI payloads."""
    metadata = KnowledgeExtractionMetadata(
        provider="deterministic",
        model=None,
        elapsed_ms=0.0,
        successful=True,
        fallback=True,
        reason="rate_limit",
    )
    knowledge = _knowledge(_chunk()).model_copy(
        update={"extraction_metadata": metadata}
    )

    assert knowledge.extraction_metadata is metadata
    assert "extraction_metadata" not in knowledge.model_dump(mode="json")
    with pytest.raises(ValidationError):
        metadata.reason = "timeout"
    with pytest.raises(ValidationError):
        KnowledgeExtractionMetadata(
            provider="deterministic",
            model=None,
            elapsed_ms=0.0,
            successful=True,
            fallback=False,
            reason=None,
        )
    with pytest.raises(ValidationError):
        KnowledgeExtractionMetadata(
            provider=123,  # type: ignore[arg-type]
            model=None,
            elapsed_ms=0.0,
            successful=True,
            fallback=True,
            reason="rate_limit",
        )
    with pytest.raises(ValidationError):
        KnowledgeExtractionMetadata(
            provider="deterministic",
            model=None,
            elapsed_ms=float("nan"),
            successful=True,
            fallback=True,
            reason="rate_limit",
        )
    with pytest.raises(ValidationError):
        KnowledgeExtractionMetadata(
            provider="deterministic",
            model=None,
            elapsed_ms=0.0,
            successful=True,
            fallback=True,
            reason="rate_limit",
            unexpected="value",
        )
