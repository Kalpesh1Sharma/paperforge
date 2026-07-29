"""Tests for the synchronous Groq knowledge provider."""

from copy import deepcopy
import json
import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.knowledge import (
    GroqAuthenticationError,
    GroqKnowledgeProvider,
    GroqNetworkError,
    GroqProviderError,
    GroqRateLimitError,
    GroqSchemaValidationError,
    GroqTimeoutError,
    KnowledgeExtractor,
    KnowledgeObject,
    MalformedGroqJsonError,
    MissingGroqApiKeyError,
    MissingGroqModelError,
    UnexpectedGroqResponseError,
)
from app.knowledge.providers import groq_provider
from app.models.document_chunk import DocumentChunk


def _chunk(text: str = "Confidential research evidence") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=uuid4(),
        document_filename="research.txt",
        chunk_index=0,
        text=text,
        start_char=0,
        end_char=len(text),
        word_count=len(text.split()),
        character_count=len(text),
        metadata={"source_file_type": "txt", "source_metadata": {}},
    )


def _response_content(**overrides: object) -> str:
    response: dict[str, object] = {
        "entities": ["PaperForge"],
        "facts": ["The evidence is reproducible."],
        "definitions": ["Evidence means supporting information."],
        "metrics": ["95%"],
        "dates": ["2026-07-29"],
        "references": ["https://example.com"],
        "confidence": 1.0,
    }
    response.update(overrides)
    return json.dumps(response)


class FakeCompletions:
    """Record one completion request and return a configured result."""

    def __init__(
        self,
        response: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class FakeGroqClient:
    """Minimal synchronous Groq SDK double."""

    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


@pytest.fixture
def configured_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(groq_provider.settings, "groq_api_key", "test-api-key")
    monkeypatch.setattr(groq_provider.settings, "groq_model", "test-model")


def _install_client(
    monkeypatch: pytest.MonkeyPatch,
    completions: FakeCompletions,
) -> list[dict[str, object]]:
    constructor_calls: list[dict[str, object]] = []

    def factory(**kwargs: object) -> FakeGroqClient:
        constructor_calls.append(kwargs)
        return FakeGroqClient(completions)

    monkeypatch.setattr(groq_provider, "Groq", factory)
    return constructor_calls


def _completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_successful_extraction_uses_one_deterministic_request(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    chunk = _chunk()
    before = deepcopy(chunk.model_dump(mode="python"))
    completions = FakeCompletions(response=_completion(_response_content()))
    constructor_calls = _install_client(monkeypatch, completions)
    provider = GroqKnowledgeProvider()

    result = provider.extract(chunk)

    assert isinstance(result, KnowledgeObject)
    assert result.chunk_id == chunk.chunk_id
    assert result.entities == ("PaperForge",)
    assert result.confidence == 1.0
    assert chunk.model_dump(mode="python") == before
    assert provider.__dict__ == {}
    assert constructor_calls == [{"api_key": "test-api-key", "max_retries": 0}]
    assert len(completions.calls) == 1
    request = completions.calls[0]
    assert request["model"] == "test-model"
    assert request["temperature"] == 0
    assert request["stream"] is False
    assert request["response_format"] == {"type": "json_object"}
    assert request["messages"][1]["content"] == "Confidential research evidence"
    with pytest.raises(ValidationError):
        result.confidence = 0.5
    with pytest.raises(AttributeError):
        result.entities.append("New entity")  # type: ignore[attr-defined]


def test_malformed_json_raises_provider_specific_error(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    completions = FakeCompletions(response=_completion("not-json"))
    _install_client(monkeypatch, completions)

    with pytest.raises(MalformedGroqJsonError):
        GroqKnowledgeProvider().extract(_chunk())


def test_invalid_schema_raises_provider_specific_error(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    completions = FakeCompletions(
        response=_completion(_response_content(confidence="certain", extra="field"))
    )
    _install_client(monkeypatch, completions)

    with pytest.raises(GroqSchemaValidationError):
        GroqKnowledgeProvider().extract(_chunk())


def test_missing_required_response_fields_raise_schema_error(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    completions = FakeCompletions(response=_completion(json.dumps({"confidence": 1.0})))
    _install_client(monkeypatch, completions)

    with pytest.raises(GroqSchemaValidationError):
        GroqKnowledgeProvider().extract(_chunk())


@pytest.mark.parametrize(
    ("setting_name", "error_type"),
    [
        ("groq_api_key", MissingGroqApiKeyError),
        ("groq_model", MissingGroqModelError),
    ],
)
def test_missing_configuration_prevents_a_request(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    setting_name: str,
    error_type: type[Exception],
) -> None:
    called = False

    def factory(**kwargs: object) -> FakeGroqClient:
        nonlocal called
        called = True
        raise AssertionError("SDK must not be constructed without configuration")

    monkeypatch.setattr(groq_provider.settings, setting_name, " ")
    monkeypatch.setattr(groq_provider, "Groq", factory)

    with pytest.raises(error_type):
        GroqKnowledgeProvider().extract(_chunk())

    assert not called


def test_missing_configuration_logs_only_safe_context(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chunk = _chunk("Sensitive source text")
    monkeypatch.setattr(groq_provider.settings, "groq_api_key", " ")

    with caplog.at_level(logging.ERROR, logger="app.knowledge.providers.groq_provider"):
        with pytest.raises(MissingGroqApiKeyError):
            GroqKnowledgeProvider().extract(chunk)

    assert str(chunk.chunk_id) in caplog.text
    assert "test-model" in caplog.text
    assert chunk.text not in caplog.text
    assert "test-api-key" not in caplog.text


@pytest.mark.parametrize(
    ("sdk_exception_name", "provider_error"),
    [
        ("AuthenticationError", GroqAuthenticationError),
        ("RateLimitError", GroqRateLimitError),
        ("APITimeoutError", GroqTimeoutError),
        ("APIConnectionError", GroqNetworkError),
        ("APIError", GroqProviderError),
    ],
)
def test_sdk_errors_are_mapped_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    sdk_exception_name: str,
    provider_error: type[Exception],
) -> None:
    sdk_error = type("FakeGroqSdkError", (Exception,), {})
    monkeypatch.setattr(groq_provider, sdk_exception_name, sdk_error)
    completions = FakeCompletions(error=sdk_error("sdk failure"))
    constructor_calls = _install_client(monkeypatch, completions)

    with pytest.raises(provider_error):
        GroqKnowledgeProvider().extract(_chunk())

    assert constructor_calls[0]["max_retries"] == 0
    assert len(completions.calls) == 1


@pytest.mark.parametrize(
    "completion",
    [
        SimpleNamespace(choices=[]),
        SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        ),
    ],
)
def test_unexpected_completion_response_raises_specific_error(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    completion: object,
) -> None:
    completions = FakeCompletions(response=completion)
    _install_client(monkeypatch, completions)

    with pytest.raises(UnexpectedGroqResponseError):
        GroqKnowledgeProvider().extract(_chunk())


def test_logging_does_not_include_text_or_api_key(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chunk = _chunk("Sensitive source text")
    completions = FakeCompletions(response=_completion(_response_content()))
    _install_client(monkeypatch, completions)

    with caplog.at_level(logging.INFO, logger="app.knowledge.providers.groq_provider"):
        GroqKnowledgeProvider().extract(chunk)

    assert str(chunk.chunk_id) in caplog.text
    assert "test-model" in caplog.text
    assert chunk.text not in caplog.text
    assert "test-api-key" not in caplog.text


def test_provider_integrates_with_unchanged_knowledge_extractor(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    chunk = _chunk()
    completions = FakeCompletions(response=_completion(_response_content()))
    _install_client(monkeypatch, completions)

    result = KnowledgeExtractor(GroqKnowledgeProvider()).extract(chunk)

    assert isinstance(result, KnowledgeObject)
    assert result.chunk_id == chunk.chunk_id
