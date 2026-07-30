"""Tests for deterministic Groq-backed report refinement overlays."""

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
    ReportIntelligenceBuilder,
    ReportSynthesisError,
    ResearchReport,
    SynthesisMetadata,
    SynthesisSourceEvidence,
    SynthesizedSection,
)
from app.reports import document_synthesizer
from app.reports.refinement import ReportRefiner


def _knowledge(
    chunk_id: UUID,
    *,
    entities: tuple[str, ...] = ("PaperForge",),
    facts: tuple[str, ...] = ("The service reduced latency.",),
    definitions: tuple[str, ...] = ("Evidence means supporting information.",),
    metrics: tuple[str, ...] = ("30%",),
    dates: tuple[str, ...] = ("2026-07-29",),
    references: tuple[str, ...] = ("https://example.com",),
    confidence: float = 1.0,
) -> KnowledgeObject:
    """Return one valid deterministic knowledge object."""
    return KnowledgeObject(
        chunk_id=chunk_id,
        entities=entities,
        facts=facts,
        definitions=definitions,
        metrics=metrics,
        dates=dates,
        references=references,
        confidence=confidence,
    )


def _report(
    chunk_id: UUID,
    *,
    findings: tuple[Finding, ...] | None = None,
) -> ResearchReport:
    """Return the canonical deterministic report used by synthesis tests."""
    return ResearchReport(
        title="Research Report",
        executive_summary=(
            "Research report generated from 1 extracted knowledge objects."
        ),
        findings=findings
        if findings is not None
        else (
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
    report: ResearchReport,
    knowledge_objects: tuple[KnowledgeObject, ...],
    **overrides: object,
) -> str:
    """Return valid model JSON rooted in the deterministic candidate plan."""
    plan = ReportRefiner.build_plan(report, knowledge_objects)
    candidate = plan.candidates[0]
    response: dict[str, object] = {
        "executive_summary": (
            "The source describes backend engineering work focused on APIs and "
            "middleware performance.\n\n"
            "It reports a measurable latency improvement supported by the "
            "extracted evidence."
        ),
        "finding_rewrites": [
            {
                "candidate_id": candidate.candidate_id,
                "title": "Backend Platform Engineering",
                "description": (
                    "The document describes API and middleware work with a "
                    "reported latency improvement."
                ),
                "supporting_chunk_ids": [
                    str(chunk_id)
                    for chunk_id in candidate.finding.supporting_chunk_ids
                ],
            }
        ],
        "sections": [
            {
                "heading": "Professional Experience",
                "content": "The documented work covers backend APIs and middleware.",
                "supporting_chunk_ids": [str(knowledge_objects[0].chunk_id)],
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
        """Return the configured completion or raise the configured SDK error."""
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
    """Configure non-secret, deterministic settings for mocked SDK calls."""
    monkeypatch.setattr(document_synthesizer.settings, "groq_api_key", "test-api-key")
    monkeypatch.setattr(document_synthesizer.settings, "groq_model", "test-model")


def _install_client(
    monkeypatch: pytest.MonkeyPatch,
    completions: FakeCompletions,
) -> list[dict[str, object]]:
    """Install a client factory and return its constructor-call ledger."""
    constructor_calls: list[dict[str, object]] = []

    def factory(**kwargs: object) -> FakeGroqClient:
        constructor_calls.append(kwargs)
        return FakeGroqClient(completions)

    monkeypatch.setattr(document_synthesizer, "Groq", factory)
    return constructor_calls


def _completion(content: str) -> SimpleNamespace:
    """Build a minimal SDK completion-shaped object."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _plan(
    report: ResearchReport,
    knowledge_objects: tuple[KnowledgeObject, ...],
) -> object:
    """Build the deterministic reference plan without mutating test inputs."""
    return ReportRefiner.build_plan(report, knowledge_objects)


def _assert_fallback(
    enhanced: EnhancedResearchReport,
    report: ResearchReport,
    plan: object,
    *,
    reason: str,
) -> None:
    """Assert deterministic fallback output against its canonical refinement plan."""
    assert enhanced.base_report is report
    assert enhanced.executive_summary == plan.executive_summary  # type: ignore[attr-defined]
    assert enhanced.findings == plan.findings  # type: ignore[attr-defined]
    assert enhanced.appendix_findings == plan.appendix_findings  # type: ignore[attr-defined]
    assert enhanced.sections == ()
    assert enhanced.synthesis_metadata.provider == "fallback"
    assert enhanced.synthesis_metadata.model is None
    assert enhanced.synthesis_metadata.successful is True
    assert enhanced.synthesis_metadata.enhanced is False
    assert enhanced.synthesis_metadata.fallback is True
    assert enhanced.synthesis_metadata.reason == reason
    assert enhanced.synthesis_metadata.source_evidence == plan.source_evidence  # type: ignore[attr-defined]
    assert enhanced.synthesis_metadata.elapsed_ms >= 0.0


def test_successful_synthesis_rewrites_only_canonical_candidates(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """One completion can improve wording without changing canonical evidence."""
    chunk_id = uuid4()
    knowledge = _knowledge(chunk_id)
    report = _report(chunk_id)
    plan = _plan(report, (knowledge,))
    report_before = deepcopy(report.model_dump(mode="python"))
    knowledge_before = deepcopy(knowledge.model_dump(mode="python"))
    completions = FakeCompletions(
        response=_completion(_response_content(report, (knowledge,)))
    )
    constructor_calls = _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (knowledge,),
    )

    assert isinstance(enhanced, EnhancedResearchReport)
    assert enhanced is not report
    assert enhanced.base_report is report
    assert report.model_dump(mode="python") == report_before
    assert knowledge.model_dump(mode="python") == knowledge_before
    assert enhanced.executive_summary.count("\n\n") == 1
    assert enhanced.findings[0].title == "Backend Platform Engineering"
    assert enhanced.findings[0].supporting_chunk_ids == plan.findings[0].supporting_chunk_ids  # type: ignore[attr-defined]
    assert enhanced.appendix_findings == plan.appendix_findings  # type: ignore[attr-defined]
    assert enhanced.sections[0].supporting_chunk_ids == (chunk_id,)
    assert enhanced.synthesis_metadata.provider == "groq"
    assert enhanced.synthesis_metadata.model == "test-model"
    assert enhanced.synthesis_metadata.successful is True
    assert enhanced.synthesis_metadata.enhanced is True
    assert enhanced.synthesis_metadata.fallback is False
    assert enhanced.synthesis_metadata.reason is None
    assert enhanced.synthesis_metadata.source_evidence == plan.source_evidence  # type: ignore[attr-defined]
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
    assert payload["refinement_candidates"] == [
        {
            "candidate_id": plan.candidates[0].candidate_id,  # type: ignore[attr-defined]
            "title": plan.candidates[0].finding.title,  # type: ignore[attr-defined]
            "description": plan.candidates[0].finding.description,  # type: ignore[attr-defined]
            "supporting_chunk_ids": [str(chunk_id)],
        }
    ]
    with pytest.raises(ValidationError):
        enhanced.executive_summary = "Changed"
    with pytest.raises(AttributeError):
        enhanced.sections.append(enhanced.sections[0])  # type: ignore[attr-defined]


def test_document_synthesizer_does_not_invoke_the_optional_intelligence_stage(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """Synthesis remains limited to its Groq/fallback enhancement responsibility."""
    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = _knowledge(chunk_id)
    completions = FakeCompletions(
        response=_completion(_response_content(report, (knowledge,)))
    )
    _install_client(monkeypatch, completions)

    def unexpected_build(*args: object, **kwargs: object) -> object:
        raise AssertionError("DocumentSynthesizer must not invoke intelligence.")

    monkeypatch.setattr(ReportIntelligenceBuilder, "build", unexpected_build)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (knowledge,),
    )

    assert enhanced.report_intelligence is None


def test_omitted_ai_rewrites_preserve_every_canonical_finding(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """The model cannot remove canonical groups by omitting a rewrite."""
    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = _knowledge(chunk_id)
    plan = _plan(report, (knowledge,))
    content = _response_content(
        report,
        (knowledge,),
        finding_rewrites=[],
        sections=[],
    )
    completions = FakeCompletions(response=_completion(content))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (knowledge,),
    )

    assert enhanced.findings == plan.findings  # type: ignore[attr-defined]
    assert enhanced.appendix_findings == plan.appendix_findings  # type: ignore[attr-defined]
    assert enhanced.sections == ()


def test_successful_synthesis_snapshots_full_source_evidence(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """Successful overlays retain all ordered source evidence for citations."""
    first_id = uuid4()
    second_id = uuid4()
    first = _knowledge(first_id, confidence=0.25, references=("Reference A",))
    second = _knowledge(second_id, confidence=0.75, references=("Reference B",))
    report = _report(first_id)
    content = _response_content(report, (first, second), finding_rewrites=[], sections=[])
    completions = FakeCompletions(response=_completion(content))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (first, second),
    )

    assert enhanced.synthesis_metadata.source_evidence == (
        SynthesisSourceEvidence(
            chunk_id=first_id,
            confidence=0.25,
            references=("Reference A",),
        ),
        SynthesisSourceEvidence(
            chunk_id=second_id,
            confidence=0.75,
            references=("Reference B",),
        ),
    )


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("not-json", "malformed_response"),
        (
            json.dumps({"executive_summary": "Only one paragraph."}),
            "validation_failure",
        ),
    ],
)
def test_malformed_json_and_schema_use_refined_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    content: str,
    reason: str,
) -> None:
    """Malformed model output produces complete deterministic refined output."""
    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = _knowledge(chunk_id)
    plan = _plan(report, (knowledge,))
    completions = FakeCompletions(response=_completion(content))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (knowledge,),
    )

    _assert_fallback(enhanced, report, plan, reason=reason)
    assert enhanced.executive_summary != report.executive_summary
    assert "generated from" not in enhanced.executive_summary.lower()
    assert len(completions.calls) == 1


@pytest.mark.parametrize(
    "summary",
    [
        "Only one paragraph.",
        "\n\n".join(f"Paragraph {index}." for index in range(5)),
    ],
)
def test_invalid_ai_summary_uses_refined_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    summary: str,
) -> None:
    """Two-to-four paragraphs remain an AI-response quality requirement."""
    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = _knowledge(chunk_id)
    plan = _plan(report, (knowledge,))
    completions = FakeCompletions(
        response=_completion(
            _response_content(report, (knowledge,), executive_summary=summary)
        )
    )
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(
        report,
        (knowledge,),
    )

    _assert_fallback(enhanced, report, plan, reason="validation_failure")


def test_unknown_or_incompatible_candidate_rewrites_use_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """Unknown, duplicate, or evidence-changing rewrites cannot alter findings."""
    first_id = uuid4()
    second_id = uuid4()
    report = _report(first_id)
    knowledge = (_knowledge(first_id), _knowledge(second_id))
    plan = _plan(report, knowledge)
    candidate = plan.candidates[0]  # type: ignore[attr-defined]
    invalid_rewrites = [
        {
            "candidate_id": "finding-unknown",
            "title": "Unknown",
            "description": "Unsupported grouping.",
            "supporting_chunk_ids": [str(first_id)],
        },
        {
            "candidate_id": candidate.candidate_id,
            "title": "Changed Evidence",
            "description": "The rewrite changes evidence membership.",
            "supporting_chunk_ids": [str(second_id)],
        },
    ]
    completions = FakeCompletions(
        response=_completion(
            _response_content(
                report,
                knowledge,
                finding_rewrites=invalid_rewrites,
                sections=[],
            )
        )
    )
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(report, knowledge)

    _assert_fallback(enhanced, report, plan, reason="validation_failure")


def test_duplicate_candidate_rewrite_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """A candidate may be rewritten at most once in the model response."""
    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = (_knowledge(chunk_id),)
    plan = _plan(report, knowledge)
    candidate = plan.candidates[0]  # type: ignore[attr-defined]
    rewrite = {
        "candidate_id": candidate.candidate_id,
        "title": "Same Group",
        "description": "The service reduced latency.",
        "supporting_chunk_ids": [str(chunk_id)],
    }
    completions = FakeCompletions(
        response=_completion(
            _response_content(
                report,
                knowledge,
                finding_rewrites=[rewrite, rewrite],
                sections=[],
            )
        )
    )
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(report, knowledge)

    _assert_fallback(enhanced, report, plan, reason="validation_failure")


def test_reordered_candidate_provenance_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """A rewrite must retain the canonical source UUID order as well as membership."""
    first_id = uuid4()
    second_id = uuid4()
    report = _report(
        first_id,
        findings=(
            Finding(
                title="Finding 1",
                description="The service reduced latency.",
                supporting_chunk_ids=(first_id,),
            ),
            Finding(
                title="Finding 2",
                description="The service reduced latency.",
                supporting_chunk_ids=(second_id,),
            ),
        ),
    )
    knowledge = (_knowledge(first_id), _knowledge(second_id))
    plan = _plan(report, knowledge)
    candidate = plan.candidates[0]  # type: ignore[attr-defined]
    assert candidate.finding.supporting_chunk_ids == (first_id, second_id)
    completions = FakeCompletions(
        response=_completion(
            _response_content(
                report,
                knowledge,
                finding_rewrites=[
                    {
                        "candidate_id": candidate.candidate_id,
                        "title": "Reordered Evidence",
                        "description": "The service reduced latency.",
                        "supporting_chunk_ids": [str(second_id), str(first_id)],
                    }
                ],
                sections=[],
            )
        )
    )
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(report, knowledge)

    _assert_fallback(enhanced, report, plan, reason="validation_failure")


@pytest.mark.parametrize(
    "sections",
    [
        [
            {
                "heading": "Unsupported",
                "content": "Unsupported source.",
                "supporting_chunk_ids": [],
            }
        ],
        [
            {
                "heading": "Unsupported",
                "content": "Unsupported source.",
                "supporting_chunk_ids": [str(uuid4())],
            }
        ],
    ],
)
def test_invalid_section_provenance_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    sections: list[dict[str, object]],
) -> None:
    """Unsupported thematic sections reject the entire model response."""
    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = (_knowledge(chunk_id),)
    plan = _plan(report, knowledge)
    completions = FakeCompletions(
        response=_completion(
            _response_content(report, knowledge, finding_rewrites=[], sections=sections)
        )
    )
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(report, knowledge)

    _assert_fallback(enhanced, report, plan, reason="validation_failure")


def test_malformed_completion_uses_refined_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """A missing completion choice is recoverable after valid input/refinement."""
    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = (_knowledge(chunk_id),)
    plan = _plan(report, knowledge)
    completions = FakeCompletions(response=SimpleNamespace(choices=[]))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(report, knowledge)

    _assert_fallback(enhanced, report, plan, reason="malformed_response")


@pytest.mark.parametrize(
    ("exception_name", "reason"),
    [
        ("RateLimitError", "rate_limit"),
        ("APITimeoutError", "timeout"),
        ("APIConnectionError", "connection"),
    ],
)
def test_transient_provider_failures_use_refined_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    exception_name: str,
    reason: str,
) -> None:
    """Only the approved transient provider errors fall back safely."""
    class TransientFailure(Exception):
        """Local SDK failure type used to exercise the explicit boundary."""

    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = (_knowledge(chunk_id),)
    plan = _plan(report, knowledge)
    monkeypatch.setattr(document_synthesizer, exception_name, TransientFailure)
    completions = FakeCompletions(error=TransientFailure("temporary failure"))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(report, knowledge)

    _assert_fallback(enhanced, report, plan, reason=reason)
    assert len(completions.calls) == 1


def test_server_status_failure_uses_refined_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """Only a five-hundred-class status error is a recoverable service failure."""
    class ServerFailure(Exception):
        """A status-bearing local SDK error double."""

        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            super().__init__(f"HTTP {status_code}")

    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = (_knowledge(chunk_id),)
    plan = _plan(report, knowledge)
    monkeypatch.setattr(document_synthesizer, "APIStatusError", ServerFailure)
    completions = FakeCompletions(error=ServerFailure(503))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(report, knowledge)

    _assert_fallback(enhanced, report, plan, reason="api_status")


def test_token_limit_status_failure_uses_a_refined_rate_limit_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """Groq's 413 token limit body is a transient rate limit, not a bad request."""
    class TokenLimitFailure(Exception):
        """A Groq-shaped token-per-minute status failure double."""

        status_code = 413
        body = {"error": {"code": "rate_limit_exceeded"}}

    chunk_id = uuid4()
    report = _report(chunk_id)
    knowledge = (_knowledge(chunk_id),)
    plan = _plan(report, knowledge)
    monkeypatch.setattr(document_synthesizer, "APIStatusError", TokenLimitFailure)
    completions = FakeCompletions(error=TokenLimitFailure("request too large"))
    _install_client(monkeypatch, completions)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(report, knowledge)

    _assert_fallback(enhanced, report, plan, reason="rate_limit")


@pytest.mark.parametrize("status_code", [401, 403, 404, 413])
def test_non_transient_status_failures_do_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    status_code: int,
) -> None:
    """Credential, permission, and other four-hundred errors still surface."""
    class ClientStatusFailure(Exception):
        """A non-recoverable status-bearing SDK error double."""

        def __init__(self, value: int) -> None:
            self.status_code = value
            super().__init__(f"HTTP {value}")

    chunk_id = uuid4()
    monkeypatch.setattr(document_synthesizer, "APIStatusError", ClientStatusFailure)
    completions = FakeCompletions(error=ClientStatusFailure(status_code))
    _install_client(monkeypatch, completions)

    with pytest.raises(ReportSynthesisError):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )


def test_authentication_and_generic_api_failures_do_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """Authentication and unclassified SDK failures remain visible to callers."""
    class AuthenticationFailure(Exception):
        """A local authentication SDK error double."""

    class GenericApiFailure(Exception):
        """A provider failure outside the transient recovery contract."""

    chunk_id = uuid4()
    monkeypatch.setattr(document_synthesizer, "AuthenticationError", AuthenticationFailure)
    auth_completions = FakeCompletions(error=AuthenticationFailure("invalid key"))
    _install_client(monkeypatch, auth_completions)
    with pytest.raises(ReportSynthesisError, match="authentication"):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )

    monkeypatch.setattr(document_synthesizer, "APIError", GenericApiFailure)
    api_completions = FakeCompletions(error=GenericApiFailure("unclassified"))
    _install_client(monkeypatch, api_completions)
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
    """Programming errors must not be hidden behind a fallback report."""
    chunk_id = uuid4()
    completions = FakeCompletions(error=error)
    _install_client(monkeypatch, completions)

    with pytest.raises(type(error)):
        document_synthesizer.DocumentSynthesizer().synthesize(
            _report(chunk_id),
            (_knowledge(chunk_id),),
        )


def test_malformed_inputs_and_missing_config_prevent_a_groq_request(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """Invalid caller inputs and configuration errors are never fallback cases."""
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

    monkeypatch.setattr(document_synthesizer.settings, "groq_api_key", " ")
    with pytest.raises(ReportSynthesisError, match="GROQ_API_KEY"):
        synthesizer.synthesize(_report(chunk_id), (_knowledge(chunk_id),))
    assert not called


def test_base_claims_must_reference_the_supplied_knowledge_objects(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """Refinement never emits a citation whose evidence is unavailable."""
    known_chunk_id = uuid4()
    unknown_chunk_id = uuid4()
    report = _report(
        known_chunk_id,
        findings=(
            Finding(
                title="Unsupported claim",
                description="This claim has no supplied source evidence.",
                supporting_chunk_ids=(unknown_chunk_id,),
            ),
        ),
    )
    calls = _install_client(monkeypatch, FakeCompletions())

    with pytest.raises(ReportSynthesisError, match="provenance"):
        document_synthesizer.DocumentSynthesizer().synthesize(
            report,
            (_knowledge(known_chunk_id),),
        )

    assert calls == []


def test_refined_fallback_is_deterministic_and_preserves_source_evidence(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
) -> None:
    """Frozen timing makes equivalent transient failures produce equal overlays."""
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
    plan = _plan(report, (first, second))
    monkeypatch.setattr(document_synthesizer, "APIConnectionError", ConnectionFailure)
    completions = FakeCompletions(error=ConnectionFailure("offline"))
    _install_client(monkeypatch, completions)
    monkeypatch.setattr(document_synthesizer, "perf_counter", lambda: 10.0)
    source_before = tuple(item.model_dump(mode="python") for item in (first, second))

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
    _assert_fallback(first_result, report, plan, reason="connection")
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
    assert tuple(item.model_dump(mode="python") for item in (first, second)) == source_before


def test_fallback_logs_one_safe_structured_warning(
    monkeypatch: pytest.MonkeyPatch,
    configured_groq: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Fallback telemetry includes safe state but never model/source payloads."""
    class TimeoutFailure(Exception):
        """A local timeout SDK error double."""

    chunk_id = uuid4()
    private_fact = "Never include this source text in logs."
    report = _report(chunk_id)
    knowledge = (_knowledge(chunk_id, facts=(private_fact,)),)
    monkeypatch.setattr(document_synthesizer, "APITimeoutError", TimeoutFailure)
    completions = FakeCompletions(error=TimeoutFailure("timeout detail"))
    _install_client(monkeypatch, completions)
    caplog.set_level(logging.WARNING, logger=document_synthesizer.__name__)

    enhanced = document_synthesizer.DocumentSynthesizer().synthesize(report, knowledge)

    _assert_fallback(enhanced, report, _plan(report, knowledge), reason="timeout")
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


def test_enhanced_models_remain_strict_and_immutable() -> None:
    """Existing enhancement and operational models retain their strict contract."""
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
        evidence.confidence = 0.5
