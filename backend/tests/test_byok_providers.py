"""Provider-neutral BYOK routing and transport tests."""

import json
from uuid import uuid4

import httpx
import pytest

from app.ai.compatible_client import CompatibleChatClient
from app.ai.configuration import (
    ProviderConfiguration,
    configured_provider,
    configured_provider_order,
)
from app.ai.exceptions import (
    CompatibleAIConfigurationError,
    CompatibleAIRateLimitError,
)
from app.ai.gemini_client import GeminiNativeChatClient
from app.ai.factory import build_provider_collaborators
from app.config import Settings, settings
from app.knowledge.exceptions import ProviderAuthenticationError
from app.knowledge.models import KnowledgeExtractionMetadata
from app.knowledge.providers import (
    CompatibleKnowledgeProvider,
    DeterministicKnowledgeProvider,
    FailoverKnowledgeProvider,
)
from app.knowledge.models import KnowledgeObject
from app.models.document_chunk import DocumentChunk
from app.reports.document_synthesizer import DocumentSynthesizer
from app.reports.deterministic_document_synthesizer import (
    DeterministicDocumentSynthesizer,
)
from app.reports.enhanced_models import EnhancedResearchReport, SynthesisMetadata
from app.reports.exceptions import ReportSynthesisError
from app.reports.failover_document_synthesizer import FailoverDocumentSynthesizer
from app.reports.models import Finding, ResearchReport


def _configuration(**updates: object) -> ProviderConfiguration:
    values = {
        "name": "gemini",
        "api_key": "private-test-key",
        "model": "test-model",
        "base_url": "https://example.test/v1",
    }
    values.update(updates)
    return ProviderConfiguration(**values)  # type: ignore[arg-type]


def _client(handler: httpx.MockTransport, **updates: object) -> CompatibleChatClient:
    return CompatibleChatClient(
        _configuration(**updates),
        client=httpx.Client(transport=handler),
        sleep=lambda _: None,
    )


@pytest.mark.parametrize("provider", ["mistral", "openai_compatible"])
def test_compatible_client_sends_expected_json_without_key_in_body(
    provider: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer private-test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "test-model"
        assert payload["response_format"] == {"type": "json_object"}
        assert "private-test-key" not in request.content.decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok":true}'}}]},
        )

    client = _client(httpx.MockTransport(handler), name=provider)
    assert client.complete([{"role": "user", "content": "source"}]) == '{"ok":true}'


def test_gemini_native_client_uses_aq_compatible_header_and_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == (
            "https://generativelanguage.googleapis.com/v1beta/"
            "models/gemini-test:generateContent"
        )
        assert request.headers["x-goog-api-key"] == "private-test-key"
        assert "Authorization" not in request.headers
        payload = json.loads(request.content)
        assert payload["system_instruction"]["parts"][0]["text"] == "System"
        assert payload["contents"][0]["parts"][0]["text"] == "Source"
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "{}"}]}}
                ]
            },
        )

    client = GeminiNativeChatClient(
        _configuration(
            model="gemini-test",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    assert client.complete(
        [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Source"},
        ]
    ) == "{}"


def test_gemini_rejection_logs_only_sanitized_status_fields(caplog) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            400,
            json=[
                {
                    "error": {
                        "code": 400,
                        "status": "INVALID_ARGUMENT",
                        "message": "Please pass private-test-key",
                    }
                }
            ],
        )
    )
    client = GeminiNativeChatClient(
        _configuration(name="gemini"),
        client=httpx.Client(transport=transport),
        sleep=lambda _: None,
    )

    with caplog.at_level("WARNING", logger="app.ai.gemini_client"):
        with pytest.raises(Exception):
            client.complete([{"role": "user", "content": "secret source"}])

    log_text = caplog.text
    assert "INVALID_ARGUMENT" in log_text
    assert "private-test-key" not in log_text
    assert "secret source" not in log_text


def test_compatible_client_retries_rate_limit_then_succeeds() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
        )

    client = _client(httpx.MockTransport(handler))
    assert client.complete([{"role": "user", "content": "source"}]) == "{}"
    assert calls == 3


def test_compatible_client_exposes_exhausted_rate_limit() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(429))
    client = _client(transport)
    with pytest.raises(CompatibleAIRateLimitError):
        client.complete([{"role": "user", "content": "source"}])


@pytest.mark.parametrize(
    "base_url",
    ["http://example.com/v1", "ftp://example.com/v1", "https://user:pass@example.com/v1"],
)
def test_compatible_client_rejects_unsafe_base_urls(base_url: str) -> None:
    with pytest.raises(CompatibleAIConfigurationError):
        _client(httpx.MockTransport(lambda _: httpx.Response(200)), base_url=base_url)


def test_compatible_knowledge_provider_records_selected_provider() -> None:
    content = json.dumps(
        {
            "entities": ["PaperForge"],
            "facts": ["The report is source grounded."],
            "definitions": [],
            "metrics": [],
            "dates": [],
            "references": [],
            "confidence": 0.9,
        }
    )
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )
    )
    provider = CompatibleKnowledgeProvider(_client(transport))
    text = "PaperForge creates source-grounded reports."
    chunk = DocumentChunk(
        chunk_id=uuid4(),
        document_filename="source.pdf",
        chunk_index=0,
        text=text,
        start_char=0,
        end_char=len(text),
        word_count=4,
        character_count=len(text),
    )

    result = provider.extract(chunk)

    assert result.extraction_metadata is not None
    assert result.extraction_metadata.provider == "gemini"
    assert result.extraction_metadata.model == "test-model"


def test_document_synthesis_records_selected_compatible_provider() -> None:
    chunk_id = uuid4()
    knowledge = (
        KnowledgeObject(
            chunk_id=chunk_id,
            facts=("The report is source grounded.",),
            confidence=0.9,
        ),
    )
    report = ResearchReport(
        title="Research Report",
        executive_summary="Generated from source evidence.",
        findings=(
            Finding(
                title="Finding 1",
                description="The report is source grounded.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
    )
    response = json.dumps(
        {
            "executive_summary": "The evidence supports the report.\n\nThe finding remains source grounded.",
            "finding_rewrites": [],
            "sections": [],
        }
    )
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={"choices": [{"message": {"content": response}}]},
        )
    )

    result = DocumentSynthesizer(_client(transport)).synthesize(report, knowledge)

    assert result.synthesis_metadata.provider == "gemini"
    assert result.synthesis_metadata.model == "test-model"
    assert result.synthesis_metadata.enhanced is True


def test_deterministic_factory_requires_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "deterministic")
    collaborators = build_provider_collaborators()
    assert isinstance(collaborators.knowledge_provider, DeterministicKnowledgeProvider)
    assert isinstance(
        collaborators.document_synthesizer, DeterministicDocumentSynthesizer
    )


def test_gemini_configuration_uses_backend_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "secret")
    monkeypatch.setattr(settings, "gemini_model", "gemini-test")
    configured = configured_provider()
    assert configured.name == "gemini"
    assert configured.api_key == "secret"
    assert configured.model == "gemini-test"


def test_gemini_default_model_matches_verified_google_ai_studio_model() -> None:
    assert Settings(_env_file=None).gemini_model == "gemini-3.6-flash"


def test_provider_order_is_deduplicated_and_always_ends_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ai_provider", "groq")
    monkeypatch.setattr(
        settings,
        "ai_provider_order",
        "gemini,mistral,gemini,openai_compatible",
    )

    assert tuple(item.name for item in configured_provider_order()) == (
        "gemini",
        "mistral",
        "openai_compatible",
        "deterministic",
    )


def test_knowledge_failover_advances_after_authentication_failure() -> None:
    calls: list[str] = []
    chunk = _chunk()

    class Rejected:
        def extract(self, _: DocumentChunk) -> KnowledgeObject:
            calls.append("gemini")
            raise ProviderAuthenticationError("secret provider detail")

    class Accepted:
        def extract(self, received: DocumentChunk) -> KnowledgeObject:
            calls.append("mistral")
            return KnowledgeObject(
                chunk_id=received.chunk_id,
                facts=("Grounded evidence.",),
                confidence=0.9,
                extraction_metadata=KnowledgeExtractionMetadata(
                    provider="mistral",
                    model="test-model",
                    elapsed_ms=1.0,
                    successful=True,
                ),
            )

    provider = FailoverKnowledgeProvider(
        (("gemini", Rejected()), ("mistral", Accepted())),  # type: ignore[arg-type]
        DeterministicKnowledgeProvider(),
    )
    result = provider.extract(chunk)

    assert calls == ["gemini", "mistral"]
    assert result.extraction_metadata is not None
    assert result.extraction_metadata.provider == "mistral"


def test_knowledge_failover_always_completes_locally() -> None:
    class Rejected:
        def extract(self, _: DocumentChunk) -> KnowledgeObject:
            raise ProviderAuthenticationError("bad key")

    result = FailoverKnowledgeProvider(
        (("gemini", Rejected()),),  # type: ignore[arg-type]
        DeterministicKnowledgeProvider(),
    ).extract(_chunk())

    assert result.extraction_metadata is not None
    assert result.extraction_metadata.provider == "deterministic"
    assert result.extraction_metadata.reason == "providers_exhausted"


def test_document_failover_advances_to_next_provider() -> None:
    chunk_id = uuid4()
    knowledge = (KnowledgeObject(chunk_id=chunk_id, facts=("Fact.",), confidence=0.9),)
    report = ResearchReport(
        title="Research Report",
        executive_summary="Evidence summary.",
        findings=(
            Finding(
                title="Finding",
                description="Fact.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
    )
    calls: list[str] = []

    class Rejected:
        def synthesize(self, *_: object) -> EnhancedResearchReport:
            calls.append("gemini")
            raise ReportSynthesisError("bad key")

    class Accepted:
        def synthesize(self, *_: object) -> EnhancedResearchReport:
            calls.append("mistral")
            return EnhancedResearchReport(
                base_report=report,
                executive_summary="Grounded summary.",
                findings=report.findings,
                synthesis_metadata=SynthesisMetadata(
                    provider="mistral",
                    model="test-model",
                    elapsed_ms=1.0,
                    successful=True,
                ),
            )

    result = FailoverDocumentSynthesizer(
        (("gemini", Rejected()), ("mistral", Accepted()))  # type: ignore[arg-type]
    ).synthesize(report, knowledge)

    assert calls == ["gemini", "mistral"]
    assert result.synthesis_metadata.provider == "mistral"


def test_document_failover_never_surfaces_provider_failure() -> None:
    chunk_id = uuid4()
    knowledge = (KnowledgeObject(chunk_id=chunk_id, facts=("Fact.",), confidence=0.9),)
    report = ResearchReport(
        title="Research Report",
        executive_summary="Evidence summary.",
        findings=(
            Finding(
                title="Finding",
                description="Fact.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
    )

    class Rejected:
        def synthesize(self, *_: object) -> EnhancedResearchReport:
            raise ReportSynthesisError("bad key")

    result = FailoverDocumentSynthesizer(
        (("gemini", Rejected()),)  # type: ignore[arg-type]
    ).synthesize(report, knowledge)

    assert result.synthesis_metadata.provider == "fallback"
    assert result.synthesis_metadata.reason == "providers_exhausted"


def test_unknown_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "unknown")
    with pytest.raises(ValueError, match="AI_PROVIDER"):
        configured_provider()


def _chunk() -> DocumentChunk:
    text = "PaperForge retains grounded evidence from the source."
    return DocumentChunk(
        chunk_id=uuid4(),
        document_filename="source.pdf",
        chunk_index=0,
        text=text,
        start_char=0,
        end_char=len(text),
        word_count=7,
        character_count=len(text),
    )
