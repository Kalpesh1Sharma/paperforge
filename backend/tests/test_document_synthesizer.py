"""Tests for the immutable Groq document-synthesis overlay."""

from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.knowledge import KnowledgeObject
from app.reports import (
    EnhancedResearchReport,
    Finding,
    ReportSynthesisError,
    ResearchReport,
    SynthesizedSection,
    SynthesisMetadata,
)
from app.reports import document_synthesizer


def _knowledge(
    chunk_id: UUID,
    *,
    facts: tuple[str, ...] = ("The service reduced latency.",),
) -> KnowledgeObject:
    return KnowledgeObject(
        chunk_id=chunk_id,
        entities=("PaperForge",),
        facts=facts,
        definitions=("Evidence means supporting information.",),
        metrics=("30%",),
        dates=("2026-07-29",),
        references=("https://example.com",),
        confidence=1.0,
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


def test_malformed_json_and_schema_are_rejected_without_partial_output(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = _knowledge(chunk_id)

    for content in (
        "not-json",
        json.dumps({"executive_summary": "Only one paragraph."}),
        _response_content(chunk_id, unexpected="value"),
    ):
        completions = FakeCompletions(response=_completion(content))
        _install_client(monkeypatch, completions)

        with pytest.raises(ReportSynthesisError):
            document_synthesizer.DocumentSynthesizer().synthesize(report, (knowledge,))


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
def test_invalid_provenance_rejects_the_whole_response(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    response_overrides: dict[str, object],
) -> None:
    chunk_id = uuid4()
    completions = FakeCompletions(
        response=_completion(_response_content(chunk_id, **response_overrides))
    )
    _install_client(monkeypatch, completions)

    with pytest.raises(ReportSynthesisError, match="provenance"):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )


@pytest.mark.parametrize(
    "summary",
    [
        "Only one paragraph.",
        "\n\n".join(f"Paragraph {index}." for index in range(5)),
    ],
)
def test_summary_must_contain_two_to_four_paragraphs(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    summary: str,
) -> None:
    chunk_id = uuid4()
    completions = FakeCompletions(
        response=_completion(_response_content(chunk_id, executive_summary=summary))
    )
    _install_client(monkeypatch, completions)

    with pytest.raises(ReportSynthesisError, match="paragraph"):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )


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


@pytest.mark.parametrize(
    "completion_or_error",
    [
        SimpleNamespace(choices=[]),
        RuntimeError("transport failure"),
    ],
)
def test_malformed_completion_and_sdk_failure_raise_report_error(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    completion_or_error: object,
) -> None:
    chunk_id = uuid4()
    if isinstance(completion_or_error, Exception):
        completions = FakeCompletions(error=completion_or_error)
    else:
        completions = FakeCompletions(response=completion_or_error)
    _install_client(monkeypatch, completions)

    with pytest.raises(ReportSynthesisError):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )

    assert len(completions.calls) == 1
