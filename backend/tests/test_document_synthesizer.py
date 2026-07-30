"""Tests for the immutable Groq document-synthesis overlay."""

from copy import deepcopy
import json
import logging
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.knowledge import KnowledgeObject
from app.reports import (
    EnhancedResearchReport,
    Finding,
    HTMLRenderer,
    MarkdownRenderer,
    ReportSynthesisError,
    ResearchReport,
    SynthesizedSection,
    SynthesisMetadata,
    SynthesisSourceEvidence,
)
from app.reports import document_synthesizer


def _knowledge(
    chunk_id: UUID,
    *,
    facts: tuple[str, ...] = ("The service reduced latency.",),
    references: tuple[str, ...] = ("https://example.com",),
    confidence: float = 1.0,
) -> KnowledgeObject:
    return KnowledgeObject(
        chunk_id=chunk_id,
        entities=("PaperForge",),
        facts=facts,
        definitions=("Evidence means supporting information.",),
        metrics=("30%",),
        dates=("2026-07-29",),
        references=references,
        confidence=confidence,
    )


def _report(chunk_id: UUID) -> ResearchReport:
    return ResearchReport(
        title="Research Report",
        executive_summary=(
            "Research report generated from 1 extracted knowledge objects."
        ),
        findings=(
            Finding(
                title="Finding 1",
                description="The service reduced latency.",
                supporting_chunk_ids=(chunk_id,),
            ),
        ),
        important_entities=("PaperForge",),
        important_definitions=("Evidence means supporting information.",),
        important_metrics=("30%",),
        timeline=(),
        references=("https://example.com",),
        sections=(),
    )


def _response_content(
    chunk_id: UUID,
    **overrides: object,
) -> str:
    response: dict[str, object] = {
        "executive_summary": (
            "The source describes backend engineering work focused on APIs and "
            "middleware performance.\n\n"
            "It reports a measurable latency improvement supported by the "
            "extracted evidence."
        ),
        "findings": [
            {
                "title": "Backend Platform Engineering",
                "description": (
                    "The document describes API and middleware work with a "
                    "reported latency improvement."
                ),
                "supporting_chunk_ids": [str(chunk_id)],
            }
        ],
        "sections": [
            {
                "heading": "Professional Experience",
                "content": "The documented work covers backend APIs and middleware.",
                "supporting_chunk_ids": [str(chunk_id)],
            }
        ],
    }
    response.update(overrides)
    return json.dumps(response)


class FakeCompletions:
    """Minimal completion double that records the exact request."""

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
    """Minimal synchronous Groq client double."""

    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


@pytest.fixture
def configured_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        document_synthesizer.settings,
        "groq_api_key",
        "test-api-key",
    )
    monkeypatch.setattr(
        document_synthesizer.settings,
        "groq_model",
        "test-model",
    )


def _install_client(
    monkeypatch: pytest.MonkeyPatch,
    completions: FakeCompletions,
) -> list[dict[str, object]]:
    constructor_calls: list[dict[str, object]] = []

    def factory(**kwargs: object) -> FakeGroqClient:
        constructor_calls.append(kwargs)
        return FakeGroqClient(completions)

    monkeypatch.setattr(document_synthesizer, "Groq", factory)
    return constructor_calls


def _completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _assert_fallback(
    enhanced: EnhancedResearchReport,
    report: ResearchReport,
    *,
    reason: str,
) -> None:
    """Assert the invariant deterministic overlay returned after a safe failure."""
    assert enhanced.base_report is report
    assert enhanced.executive_summary == report.executive_summary
    assert enhanced.findings == report.findings
    assert enhanced.sections == ()
    assert enhanced.synthesis_metadata.provider == "fallback"
    assert enhanced.synthesis_metadata.model is None
    assert enhanced.synthesis_metadata.successful is True
    assert enhanced.synthesis_metadata.enhanced is False
    assert enhanced.synthesis_metadata.fallback is True
    assert enhanced.synthesis_metadata.reason == reason
    assert enhanced.synthesis_metadata.elapsed_ms >= 0.0


def test_successful_synthesis_preserves_base_report_and_source_objects(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    chunk_id = uuid4()
    knowledge = _knowledge(chunk_id)
    report = _report(chunk_id)
    report_before = deepcopy(report.model_dump(mode="python"))
    knowledge_before = deepcopy(knowledge.model_dump(mode="python"))
    completions = FakeCompletions(response=_completion(_response_content(chunk_id)))
    constructor_calls = _install_client(monkeypatch, completions)
    synthesizer = document_synthesizer.DocumentSynthesizer()

    enhanced = synthesizer.synthesize(report, (knowledge,))

    assert isinstance(enhanced, EnhancedResearchReport)
    assert enhanced is not report
    assert enhanced.base_report is report
    assert report.model_dump(mode="python") == report_before
    assert knowledge.model_dump(mode="python") == knowledge_before
    assert enhanced.executive_summary.count("\n\n") == 1
    assert enhanced.findings[0].supporting_chunk_ids == (chunk_id,)
    assert enhanced.sections[0].supporting_chunk_ids == (chunk_id,)
    assert enhanced.synthesis_metadata.provider == "groq"
    assert enhanced.synthesis_metadata.model == "test-model"
    assert enhanced.synthesis_metadata.elapsed_ms >= 0.0
    assert enhanced.synthesis_metadata.successful is True
    assert enhanced.synthesis_metadata.enhanced is True
    assert enhanced.synthesis_metadata.fallback is False
    assert enhanced.synthesis_metadata.reason is None
    assert enhanced.synthesis_metadata.source_evidence == ()
    assert constructor_calls == [{"api_key": "test-api-key", "max_retries": 0}]
    assert len(completions.calls) == 1
    request = completions.calls[0]
    assert request["model"] == "test-model"
    assert request["temperature"] == 0
    assert request["stream"] is False
    assert request["response_format"] == {"type": "json_object"}
    payload = json.loads(request["messages"][1]["content"])
    assert payload["report"]["title"] == report.title
    assert payload["knowledge_objects"][0]["chunk_id"] == str(chunk_id)
    with pytest.raises(ValidationError):
        enhanced.executive_summary = "Changed"
    with pytest.raises(AttributeError):
        enhanced.sections.append(enhanced.sections[0])  # type: ignore[attr-defined]


def test_enhanced_models_reject_blank_content_and_empty_provenance() -> None:
    chunk_id = uuid4()
    evidence = SynthesisSourceEvidence(
        chunk_id=chunk_id,
        confidence=1.0,
        references=("Reference A",),
    )

    with pytest.raises(ValidationError):
        SynthesizedSection(
            heading=" ",
            content="Grounded content.",
            supporting_chunk_ids=(chunk_id,),
        )
    with pytest.raises(ValidationError):
        SynthesizedSection(
            heading="Grounded heading",
            content="Grounded content.",
            supporting_chunk_ids=(),
        )
    with pytest.raises(ValidationError):
        SynthesisMetadata(
            provider=" ",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        )
    with pytest.raises(ValidationError):
        SynthesisSourceEvidence(
            chunk_id=chunk_id,
            confidence=1.1,
            references=(),
        )
    with pytest.raises(ValidationError):
        SynthesisSourceEvidence(
            chunk_id=chunk_id,
            confidence=1.0,
            references=(),
            unexpected=True,
        )
    with pytest.raises(ValidationError):
        evidence.confidence = 0.5
    fallback_metadata = SynthesisMetadata(
        provider="fallback",
        model=None,
        elapsed_ms=0.0,
        successful=True,
        enhanced=False,
        fallback=True,
        reason="timeout",
        source_evidence=(evidence,),
    )
    with pytest.raises(ValidationError):
        fallback_metadata.reason = "connection"
    with pytest.raises(ValidationError):
        SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
            unexpected=True,
        )
    with pytest.raises(ValidationError):
        SynthesisMetadata(
            provider="fallback",
            model=None,
            elapsed_ms=0.0,
            successful=True,
            enhanced=False,
            fallback=True,
            reason="invalid reason",
            source_evidence=(
                SynthesisSourceEvidence(
                    chunk_id=chunk_id,
                    confidence=1.0,
                    references=(),
                ),
            ),
        )


def test_synthesis_is_stable_for_identical_mocked_content(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = _knowledge(chunk_id)
    completions = FakeCompletions(response=_completion(_response_content(chunk_id)))
    _install_client(monkeypatch, completions)
    synthesizer = document_synthesizer.DocumentSynthesizer()

    first = synthesizer.synthesize(report, (knowledge,))
    second = synthesizer.synthesize(report, (knowledge,))

    assert first.base_report is report
    assert second.base_report is report
    assert first.executive_summary == second.executive_summary
    assert first.findings == second.findings
    assert first.sections == second.sections
    assert first.synthesis_metadata.provider == second.synthesis_metadata.provider
    assert first.synthesis_metadata.model == second.synthesis_metadata.model
    assert first.synthesis_metadata.successful is second.synthesis_metadata.successful
    assert first.synthesis_metadata.elapsed_ms >= 0.0
    assert second.synthesis_metadata.elapsed_ms >= 0.0
    assert len(completions.calls) == 2


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("not-json", "malformed_response"),
        (
            json.dumps({"executive_summary": "Only one paragraph."}),
            "validation_failure",
        ),
        (_response_content(uuid4(), unexpected="value"), "validation_failure"),
    ],
)
def test_malformed_json_and_schema_use_a_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    content: str,
    reason: str,
) -> None:
    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = _knowledge(chunk_id)

    completions = FakeCompletions(response=_completion(content))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (knowledge,),
    )

    _assert_fallback(enhanced, report, reason=reason)
    assert enhanced.synthesis_metadata.source_evidence == (
        SynthesisSourceEvidence(
            chunk_id=knowledge.chunk_id,
            confidence=knowledge.confidence,
            references=knowledge.references,
        ),
    )
    assert len(completions.calls) == 1


@pytest.mark.parametrize(
    "response_overrides",
    [
        {
            "findings": [
                {
                    "title": "Unsupported",
                    "description": "Unsupported source.",
                    "supporting_chunk_ids": [str(uuid4())],
                }
            ]
        },
        {
            "sections": [
                {
                    "heading": "Unsupported",
                    "content": "Unsupported source.",
                    "supporting_chunk_ids": [],
                }
            ]
        },
    ],
)
def test_invalid_provenance_uses_a_fallback_without_partial_ai_content(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    response_overrides: dict[str, object],
) -> None:
    chunk_id = uuid4()
    completions = FakeCompletions(
        response=_completion(_response_content(chunk_id, **response_overrides))
    )
    _install_client(monkeypatch, completions)

    report = _report(chunk_id)
    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (_knowledge(chunk_id),),
    )

    _assert_fallback(enhanced, report, reason="validation_failure")


@pytest.mark.parametrize(
    "summary",
    [
        "Only one paragraph.",
        "\n\n".join(f"Paragraph {index}." for index in range(5)),
    ],
)
def test_invalid_ai_summary_uses_a_fallback_but_does_not_change_rendering_rules(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    summary: str,
) -> None:
    chunk_id = uuid4()
    completions = FakeCompletions(
        response=_completion(_response_content(chunk_id, executive_summary=summary))
    )
    _install_client(monkeypatch, completions)

    report = _report(chunk_id)
    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (_knowledge(chunk_id),),
    )

    _assert_fallback(enhanced, report, reason="validation_failure")
    assert MarkdownRenderer().render_enhanced(enhanced).count(
        report.executive_summary
    ) == 1
    assert report.executive_summary in HTMLRenderer().render(enhanced)


def test_malformed_inputs_prevent_a_groq_request(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    chunk_id = uuid4()
    called = False

    def factory(**kwargs: object) -> FakeGroqClient:
        nonlocal called
        called = True
        raise AssertionError("Groq must not be constructed for invalid input")

    corrupted_report_data = _report(chunk_id).model_dump(mode="python")
    corrupted_report_data["important_entities"] = ("Duplicate", "Duplicate")
    corrupted_report = ResearchReport.model_construct(**corrupted_report_data)
    corrupted_knowledge_data = _knowledge(chunk_id).model_dump(mode="python")
    corrupted_knowledge_data["facts"] = ["invalid collection"]
    corrupted_knowledge = KnowledgeObject.model_construct(**corrupted_knowledge_data)
    monkeypatch.setattr(document_synthesizer, "Groq", factory)
    synthesizer = document_synthesizer.DocumentSynthesizer()

    with pytest.raises(ReportSynthesisError):
        synthesizer.synthesize(corrupted_report, (_knowledge(chunk_id),))
    with pytest.raises(ReportSynthesisError):
        synthesizer.synthesize(_report(chunk_id), (corrupted_knowledge,))
    with pytest.raises(ReportSynthesisError, match="at least one"):
        synthesizer.synthesize(_report(chunk_id), ())

    assert not called


@pytest.mark.parametrize("setting_name", ["groq_api_key", "groq_model"])
def test_missing_configuration_prevents_a_groq_request(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    setting_name: str,
) -> None:
    chunk_id = uuid4()
    monkeypatch.setattr(document_synthesizer.settings, setting_name, " ")
    completions = FakeCompletions()
    constructor_calls = _install_client(monkeypatch, completions)

    with pytest.raises(ReportSynthesisError):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )

    assert constructor_calls == []


def test_malformed_completion_uses_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    chunk_id = uuid4()
    report = _report(chunk_id)
    completions = FakeCompletions(response=SimpleNamespace(choices=[]))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (_knowledge(chunk_id),),
    )

    _assert_fallback(enhanced, report, reason="malformed_response")
    assert len(completions.calls) == 1


@pytest.mark.parametrize(
    ("exception_name", "reason"),
    [
        ("RateLimitError", "rate_limit"),
        ("APITimeoutError", "timeout"),
        ("APIConnectionError", "connection"),
    ],
)
def test_transient_provider_failures_use_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    exception_name: str,
    reason: str,
) -> None:
    class TransientFailure(Exception):
        """A local SDK failure type used to exercise the explicit boundary."""

    chunk_id = uuid4()
    report = _report(chunk_id)
    monkeypatch.setattr(document_synthesizer, exception_name, TransientFailure)
    completions = FakeCompletions(error=TransientFailure("temporary failure"))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (_knowledge(chunk_id),),
    )

    _assert_fallback(enhanced, report, reason=reason)
    assert len(completions.calls) == 1


def test_server_status_failure_uses_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    class ServerFailure(Exception):
        """A status-bearing local SDK error double."""

        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            super().__init__(f"HTTP {status_code}")

    chunk_id = uuid4()
    report = _report(chunk_id)
    monkeypatch.setattr(document_synthesizer, "APIStatusError", ServerFailure)
    completions = FakeCompletions(error=ServerFailure(503))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (_knowledge(chunk_id),),
    )

    _assert_fallback(enhanced, report, reason="api_status")


@pytest.mark.parametrize("status_code", [401, 403, 404])
def test_non_transient_status_failures_do_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    status_code: int,
) -> None:
    class ClientStatusFailure(Exception):
        """A non-recoverable status-bearing SDK error double."""

        def __init__(self, value: int) -> None:
            self.status_code = value
            super().__init__(f"HTTP {value}")

    chunk_id = uuid4()
    monkeypatch.setattr(
        document_synthesizer,
        "APIStatusError",
        ClientStatusFailure,
    )
    completions = FakeCompletions(error=ClientStatusFailure(status_code))
    _install_client(monkeypatch, completions)

    with pytest.raises(ReportSynthesisError):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )


def test_authentication_failure_does_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    class AuthenticationFailure(Exception):
        """A local authentication SDK error double."""

    chunk_id = uuid4()
    monkeypatch.setattr(
        document_synthesizer,
        "AuthenticationError",
        AuthenticationFailure,
    )
    completions = FakeCompletions(error=AuthenticationFailure("invalid key"))
    _install_client(monkeypatch, completions)

    with pytest.raises(ReportSynthesisError, match="authentication"):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )


def test_unclassified_api_error_does_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    class GenericApiFailure(Exception):
        """A provider failure outside the transient recovery contract."""

    chunk_id = uuid4()
    monkeypatch.setattr(document_synthesizer, "APIError", GenericApiFailure)
    completions = FakeCompletions(error=GenericApiFailure("unclassified"))
    _install_client(monkeypatch, completions)

    with pytest.raises(ReportSynthesisError, match="request failed"):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("unexpected implementation failure"),
        TypeError("unexpected type failure"),
        ValueError("unexpected value failure"),
    ],
)
def test_unexpected_programming_errors_propagate(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    error: Exception,
) -> None:
    chunk_id = uuid4()
    completions = FakeCompletions(error=error)
    _install_client(monkeypatch, completions)

    with pytest.raises(type(error)):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )


def test_fallback_preserves_ordered_source_evidence_and_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    first_chunk_id = uuid4()
    second_chunk_id = uuid4()
    first = _knowledge(
        first_chunk_id,
        references=("Reference A", "Reference B"),
        confidence=0.25,
    )
    second = _knowledge(
        second_chunk_id,
        references=("Reference C",),
        confidence=0.75,
    )
    class ConnectionFailure(Exception):
        """A local connection SDK error double."""

    report = _report(first_chunk_id)
    monkeypatch.setattr(
        document_synthesizer,
        "APIConnectionError",
        ConnectionFailure,
    )
    completions = FakeCompletions(error=ConnectionFailure("offline"))
    _install_client(monkeypatch, completions)
    monkeypatch.setattr(document_synthesizer, "perf_counter", lambda: 10.0)
    source_before = tuple(
        item.model_dump(mode="python") for item in (first, second)
    )

    first_result = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (first, second),
    )
    second_result = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (first, second),
    )

    assert first_result == second_result
    assert first_result.synthesis_metadata.elapsed_ms == 0.0
    assert first_result.synthesis_metadata.source_evidence == (
        SynthesisSourceEvidence(
            chunk_id=first_chunk_id,
            confidence=0.25,
            references=("Reference A", "Reference B"),
        ),
        SynthesisSourceEvidence(
            chunk_id=second_chunk_id,
            confidence=0.75,
            references=("Reference C",),
        ),
    )
    assert tuple(
        item.model_dump(mode="python") for item in (first, second)
    ) == source_before


def test_fallback_logs_one_safe_structured_warning(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class TimeoutFailure(Exception):
        """A local timeout SDK error double."""

    chunk_id = uuid4()
    private_fact = "Never include this source text in logs."
    report = _report(chunk_id)
    knowledge = _knowledge(chunk_id, facts=(private_fact,))
    monkeypatch.setattr(document_synthesizer, "APITimeoutError", TimeoutFailure)
    completions = FakeCompletions(error=TimeoutFailure("timeout detail"))
    _install_client(monkeypatch, completions)
    caplog.set_level(logging.WARNING, logger=document_synthesizer.__name__)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (knowledge,),
    )

    _assert_fallback(enhanced, report, reason="timeout")
    warnings = [
        record
        for record in caplog.records
        if record.name == document_synthesizer.__name__
        and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "provider=groq" in message
    assert "fallback=true" in message
    assert "reason=timeout" in message
    assert private_fact not in message
    assert "test-api-key" not in message
