"""Groq-backed, immutable refinements for deterministic research reports."""

import json
import logging
import math
import re
from collections.abc import Mapping
from time import perf_counter
from uuid import UUID

from groq import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    Groq,
    RateLimitError,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from app.config import settings
from app.knowledge.models import KnowledgeObject
from app.reports.enhanced_models import (
    EnhancedResearchReport,
    SynthesisMetadata,
    SynthesizedSection,
)
from app.reports.exceptions import ReportSynthesisError
from app.reports.models import ResearchReport
from app.reports.prompts import DOCUMENT_SYNTHESIS_PROMPT
from app.reports.refinement import (
    CandidateRewrite,
    InvalidRefinementRewriteError,
    RefinementPlan,
    ReportRefiner,
)

logger = logging.getLogger(__name__)

_KNOWLEDGE_COLLECTION_FIELDS = (
    "entities",
    "facts",
    "definitions",
    "metrics",
    "dates",
    "references",
)
_PARAGRAPH_SEPARATOR = re.compile(r"\r?\n[ \t]*(?:\r?\n)+")


class _RecoverableSynthesisResponseError(ReportSynthesisError):
    """A model-response failure that may use deterministic fallback output."""

    def __init__(self, message: str, reason: str) -> None:
        """Store a normalized, safe reason for fallback telemetry."""
        super().__init__(message)
        self.reason = reason


class _SynthesisFindingRewriteResponse(BaseModel):
    """Strict private schema for one canonical-candidate rewrite."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    candidate_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    supporting_chunk_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("candidate_id", "title", "description")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        """Reject whitespace-only model output without normalizing it."""
        if not value.strip():
            raise ValueError("Generated text must not be blank.")
        return value


class _SynthesisSectionResponse(BaseModel):
    """Strict private schema for a Groq-generated report section."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    heading: str = Field(min_length=1)
    content: str = Field(min_length=1)
    supporting_chunk_ids: tuple[UUID, ...] = Field(min_length=1)

    @field_validator("heading", "content")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        """Reject whitespace-only generated content without normalizing it."""
        if not value.strip():
            raise ValueError("Generated text must not be blank.")
        return value


class _DocumentSynthesisResponse(BaseModel):
    """Strict private response contract for document-level refinement."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    executive_summary: str = Field(min_length=1)
    finding_rewrites: tuple[_SynthesisFindingRewriteResponse, ...] = Field(
        default_factory=tuple
    )
    sections: tuple[_SynthesisSectionResponse, ...] = Field(default_factory=tuple)

    @field_validator("executive_summary")
    @classmethod
    def validate_executive_summary(cls, value: str) -> str:
        """Require the requested two to four non-empty summary paragraphs."""
        if not value.strip():
            raise ValueError("Executive summary must not be blank.")

        paragraphs = tuple(
            paragraph
            for paragraph in _PARAGRAPH_SEPARATOR.split(value.strip())
            if paragraph.strip()
        )
        if not 2 <= len(paragraphs) <= 4:
            raise ValueError(
                "Executive summary must contain between two and four paragraphs."
            )
        return value


class DocumentSynthesizer:
    """Refine one deterministic report through a single Groq completion."""

    def synthesize(
        self,
        report: ResearchReport,
        knowledge_objects: tuple[KnowledgeObject, ...],
    ) -> EnhancedResearchReport:
        """Return a refined AI overlay or deterministic refined fallback.

        Input validation and deterministic refinement happen before creating a
        provider client. Only explicitly transient provider failures and invalid
        model responses use fallback output; configuration, authorization, input,
        and programming failures intentionally surface to the caller.
        """
        started_at = perf_counter()
        model = self._configured_model_name()
        object_count = self._safe_knowledge_object_count(knowledge_objects)

        self._validate_report(report)
        self._validate_knowledge_objects(knowledge_objects)
        self._validate_base_provenance(report, knowledge_objects)
        refinement_plan = ReportRefiner.build_plan(report, knowledge_objects)
        api_key, model = self._configuration()
        payload = self._request_payload(report, knowledge_objects, refinement_plan)

        try:
            client = Groq(api_key=api_key, max_retries=0)
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": DOCUMENT_SYNTHESIS_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": payload,
                    },
                ],
                temperature=0,
                stream=False,
                response_format={"type": "json_object"},
            )
            response = self._parse_response(self._completion_content(completion))
            self._validate_section_provenance(response, knowledge_objects)
            enhanced_report = self._enhanced_report(
                report,
                refinement_plan,
                response,
                model,
                started_at,
            )
        except _RecoverableSynthesisResponseError as exc:
            return self._fallback_report(
                report,
                refinement_plan,
                started_at,
                reason=exc.reason,
                message=str(exc),
            )
        except RateLimitError:
            return self._fallback_report(
                report,
                refinement_plan,
                started_at,
                reason="rate_limit",
                message="Groq document synthesis was rate limited.",
            )
        except APITimeoutError:
            return self._fallback_report(
                report,
                refinement_plan,
                started_at,
                reason="timeout",
                message="Groq document synthesis timed out.",
            )
        except AuthenticationError as exc:
            self._log_failure(model, object_count, started_at)
            raise ReportSynthesisError(
                "Groq document synthesis authentication failed."
            ) from exc
        except APIConnectionError:
            return self._fallback_report(
                report,
                refinement_plan,
                started_at,
                reason="connection",
                message="Groq document synthesis service was unreachable.",
            )
        except APIStatusError as exc:
            if self._is_rate_limit_status_error(exc):
                return self._fallback_report(
                    report,
                    refinement_plan,
                    started_at,
                    reason="rate_limit",
                    message="Groq document synthesis was rate limited.",
                )
            if self._is_server_error(exc):
                return self._fallback_report(
                    report,
                    refinement_plan,
                    started_at,
                    reason="api_status",
                    message=(
                        "Groq document synthesis service returned a server error."
                    ),
                )

            self._log_failure(model, object_count, started_at)
            status_code = getattr(exc, "status_code", None)
            if status_code == 401:
                raise ReportSynthesisError(
                    "Groq document synthesis authentication failed."
                ) from exc
            if status_code == 403:
                raise ReportSynthesisError(
                    "Groq document synthesis permission was denied."
                ) from exc
            raise ReportSynthesisError(
                "Groq document synthesis request was rejected."
            ) from exc
        except APIError as exc:
            self._log_failure(model, object_count, started_at)
            raise ReportSynthesisError(
                "Groq document synthesis request failed."
            ) from exc

        self._log_success(model, object_count, started_at)
        return enhanced_report

    @staticmethod
    def _configuration() -> tuple[str, str]:
        """Return configured Groq credentials without retaining instance state."""
        api_key = settings.groq_api_key
        if not isinstance(api_key, str) or not api_key.strip():
            raise ReportSynthesisError("GROQ_API_KEY must be configured.")

        model = settings.groq_model
        if not isinstance(model, str) or not model.strip():
            raise ReportSynthesisError("GROQ_MODEL must be configured.")

        return api_key.strip(), model.strip()

    @staticmethod
    def _configured_model_name() -> str:
        """Return a non-secret model label for safe operational logging."""
        model = settings.groq_model
        if isinstance(model, str) and model.strip():
            return model.strip()
        return "<unconfigured>"

    @staticmethod
    def _safe_knowledge_object_count(knowledge_objects: object) -> int:
        """Return a safe count for logs before validating the input contract."""
        if isinstance(knowledge_objects, tuple):
            return len(knowledge_objects)
        return 0

    @staticmethod
    def _is_server_error(error: APIStatusError) -> bool:
        """Return whether an SDK status error represents a recoverable 5xx."""
        status_code = getattr(error, "status_code", None)
        return (
            not isinstance(status_code, bool)
            and isinstance(status_code, int)
            and 500 <= status_code <= 599
        )

    @staticmethod
    def _is_rate_limit_status_error(error: APIStatusError) -> bool:
        """Recognize Groq rate limits that arrive through generic status errors.

        Groq can surface token-per-minute exhaustion as HTTP 413 with a
        ``rate_limit_exceeded`` body, rather than as the SDK's 429-specific
        ``RateLimitError``. Restrict the fallback to explicit rate-limit signals
        so unrelated client-side status errors still surface to callers.
        """
        if getattr(error, "status_code", None) == 429:
            return True

        body = getattr(error, "body", None)
        if isinstance(body, Mapping):
            details = body.get("error", body)
            if isinstance(details, Mapping):
                code = details.get("code")
                if isinstance(code, str) and code.casefold() in {
                    "rate_limit",
                    "rate_limit_exceeded",
                }:
                    return True

        return "rate_limit_exceeded" in str(error).casefold()

    @classmethod
    def _validate_report(cls, report: object) -> None:
        """Defensively validate a base report without copying or mutating it."""
        if not isinstance(report, ResearchReport):
            raise ReportSynthesisError(
                "Input report must be a ResearchReport instance."
            )
        if getattr(report, "__pydantic_extra__", None):
            raise ReportSynthesisError("ResearchReport must not contain extra fields.")

        try:
            payload = report.model_dump(mode="python", warnings="error")
            ResearchReport.model_validate(payload)
        except (AttributeError, TypeError, ValidationError, ValueError) as exc:
            raise ReportSynthesisError(
                "ResearchReport failed structural validation."
            ) from exc
        except Exception as exc:
            raise ReportSynthesisError(
                "ResearchReport could not be validated safely."
            ) from exc

    @classmethod
    def _validate_knowledge_objects(cls, knowledge_objects: object) -> None:
        """Validate tuple inputs, including validation-bypassed source models."""
        if not isinstance(knowledge_objects, tuple):
            raise ReportSynthesisError("Knowledge objects must be provided as a tuple.")
        if not knowledge_objects:
            raise ReportSynthesisError(
                "Document synthesis requires at least one KnowledgeObject."
            )

        for knowledge_object in knowledge_objects:
            cls._validate_knowledge_object(knowledge_object)

    @staticmethod
    def _validate_knowledge_object(knowledge_object: object) -> None:
        """Validate source knowledge values without changing their identities."""
        if not isinstance(knowledge_object, KnowledgeObject):
            raise ReportSynthesisError(
                "Each input item must be a KnowledgeObject instance."
            )
        if getattr(knowledge_object, "__pydantic_extra__", None):
            raise ReportSynthesisError("KnowledgeObject must not contain extra fields.")

        try:
            chunk_id = knowledge_object.chunk_id
        except AttributeError as exc:
            raise ReportSynthesisError(
                "KnowledgeObject must include a chunk_id."
            ) from exc
        if not isinstance(chunk_id, UUID):
            raise ReportSynthesisError("KnowledgeObject chunk_id must be a UUID.")

        for field_name in _KNOWLEDGE_COLLECTION_FIELDS:
            try:
                values = getattr(knowledge_object, field_name)
            except AttributeError as exc:
                raise ReportSynthesisError(
                    f"KnowledgeObject must include {field_name}."
                ) from exc

            if not isinstance(values, tuple) or any(
                not isinstance(value, str) for value in values
            ):
                raise ReportSynthesisError(
                    f"KnowledgeObject {field_name} must be a tuple of strings."
                )

        try:
            confidence = knowledge_object.confidence
        except AttributeError as exc:
            raise ReportSynthesisError(
                "KnowledgeObject must include confidence."
            ) from exc

        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, float)
            or not math.isfinite(confidence)
            or not 0.0 <= confidence <= 1.0
        ):
            raise ReportSynthesisError(
                "KnowledgeObject confidence must be a finite float from 0 to 1."
            )

    @staticmethod
    def _validate_base_provenance(
        report: ResearchReport,
        knowledge_objects: tuple[KnowledgeObject, ...],
    ) -> None:
        """Require deterministic claim provenance to be present in the sources.

        The base report is canonical, but its claim-bearing findings and timeline
        entries must still be source-addressable before they can be refined or
        rendered with human-readable citations.
        """
        known_chunk_ids = {
            knowledge_object.chunk_id for knowledge_object in knowledge_objects
        }
        for statements, statement_name in (
            (report.findings, "finding"),
            (report.timeline, "timeline event"),
        ):
            for statement in statements:
                supporting_chunk_ids = statement.supporting_chunk_ids
                if not supporting_chunk_ids:
                    raise ReportSynthesisError(
                        f"ResearchReport {statement_name} must include source "
                        "provenance."
                    )
                if not set(supporting_chunk_ids).issubset(known_chunk_ids):
                    raise ReportSynthesisError(
                        f"ResearchReport {statement_name} provenance must reference "
                        "supplied knowledge objects."
                    )

    @staticmethod
    def _request_payload(
        report: ResearchReport,
        knowledge_objects: tuple[KnowledgeObject, ...],
        refinement_plan: RefinementPlan,
    ) -> str:
        """Serialize immutable inputs and canonical candidates into one request."""
        payload = {
            "knowledge_objects": [
                knowledge_object.model_dump(mode="json", warnings="error")
                for knowledge_object in knowledge_objects
            ],
            "refinement_candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "title": candidate.finding.title,
                    "description": candidate.finding.description,
                    "supporting_chunk_ids": [
                        str(chunk_id)
                        for chunk_id in candidate.finding.supporting_chunk_ids
                    ],
                }
                for candidate in refinement_plan.candidates
            ],
            "report": report.model_dump(mode="json", warnings="error"),
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _completion_content(completion: object) -> str:
        """Extract non-empty JSON content from a synchronous SDK completion."""
        choices = getattr(completion, "choices", None)
        if not isinstance(choices, (list, tuple)) or not choices:
            raise _RecoverableSynthesisResponseError(
                "Groq response contained no choices.",
                "malformed_response",
            )

        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise _RecoverableSynthesisResponseError(
                "Groq response contained no usable message content.",
                "malformed_response",
            )
        return content

    @staticmethod
    def _parse_response(content: str) -> _DocumentSynthesisResponse:
        """Parse JSON-only model output through the strict private schema."""
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise _RecoverableSynthesisResponseError(
                "Groq response was not valid JSON.",
                "malformed_response",
            ) from exc

        try:
            return _DocumentSynthesisResponse.model_validate_json(content)
        except ValidationError as exc:
            error_locations = tuple(error.get("loc", ()) for error in exc.errors())
            if any("executive_summary" in location for location in error_locations):
                raise _RecoverableSynthesisResponseError(
                    "Groq response failed executive summary paragraph requirements.",
                    "validation_failure",
                ) from exc
            if any(
                "supporting_chunk_ids" in location for location in error_locations
            ):
                raise _RecoverableSynthesisResponseError(
                    "Groq response failed source provenance requirements.",
                    "validation_failure",
                ) from exc
            raise _RecoverableSynthesisResponseError(
                "Groq response did not match the document refinement schema.",
                "validation_failure",
            ) from exc

    @staticmethod
    def _validate_section_provenance(
        response: _DocumentSynthesisResponse,
        knowledge_objects: tuple[KnowledgeObject, ...],
    ) -> None:
        """Require every generated section to cite supplied source UUIDs."""
        source_chunk_ids = {
            knowledge_object.chunk_id for knowledge_object in knowledge_objects
        }

        for section in response.sections:
            supporting_chunk_ids = section.supporting_chunk_ids
            if not supporting_chunk_ids:
                raise _RecoverableSynthesisResponseError(
                    "Synthesized content must include source chunk provenance.",
                    "validation_failure",
                )
            if not set(supporting_chunk_ids).issubset(source_chunk_ids):
                raise _RecoverableSynthesisResponseError(
                    "Synthesized content provenance referenced an unknown source "
                    "chunk.",
                    "validation_failure",
                )

    @staticmethod
    def _candidate_rewrites(
        response: _DocumentSynthesisResponse,
    ) -> tuple[CandidateRewrite, ...]:
        """Convert validated model rewrites to the refiner's immutable contract."""
        try:
            return tuple(
                CandidateRewrite(
                    candidate_id=rewrite.candidate_id,
                    title=rewrite.title,
                    description=rewrite.description,
                    supporting_chunk_ids=rewrite.supporting_chunk_ids,
                )
                for rewrite in response.finding_rewrites
            )
        except (ValidationError, ValueError) as exc:
            raise _RecoverableSynthesisResponseError(
                "Groq response contained an invalid finding rewrite.",
                "validation_failure",
            ) from exc

    @classmethod
    def _enhanced_report(
        cls,
        report: ResearchReport,
        refinement_plan: RefinementPlan,
        response: _DocumentSynthesisResponse,
        model: str,
        started_at: float,
    ) -> EnhancedResearchReport:
        """Build a new overlay while retaining canonical candidate membership."""
        rewrites = cls._candidate_rewrites(response)
        try:
            findings, appendix_findings = ReportRefiner.apply_rewrites(
                refinement_plan,
                rewrites,
            )
        except InvalidRefinementRewriteError as exc:
            raise _RecoverableSynthesisResponseError(
                "Groq response attempted an invalid canonical finding rewrite.",
                "validation_failure",
            ) from exc

        try:
            enhanced_report = EnhancedResearchReport(
                base_report=report,
                executive_summary=response.executive_summary,
                findings=findings,
                appendix_findings=appendix_findings,
                sections=tuple(
                    SynthesizedSection(
                        heading=section.heading,
                        content=section.content,
                        supporting_chunk_ids=section.supporting_chunk_ids,
                    )
                    for section in response.sections
                ),
                synthesis_metadata=SynthesisMetadata(
                    provider="groq",
                    model=model,
                    elapsed_ms=(perf_counter() - started_at) * 1000,
                    successful=True,
                    source_evidence=refinement_plan.source_evidence,
                ),
            )
        except ValidationError as exc:
            raise _RecoverableSynthesisResponseError(
                "Unable to construct an enhanced research report.",
                "validation_failure",
            ) from exc

        if enhanced_report.base_report is not report:
            raise ReportSynthesisError(
                "EnhancedResearchReport must retain the original base report instance."
            )
        return enhanced_report

    @staticmethod
    def _fallback_report(
        report: ResearchReport,
        refinement_plan: RefinementPlan,
        started_at: float,
        *,
        reason: str,
        message: str,
    ) -> EnhancedResearchReport:
        """Build and log one deterministic refined fallback after a safe failure."""
        fallback_report = DocumentSynthesizer._build_fallback_report(
            report,
            refinement_plan,
            started_at,
            reason,
        )
        DocumentSynthesizer._log_fallback(reason, message, started_at)
        return fallback_report

    @staticmethod
    def _build_fallback_report(
        report: ResearchReport,
        refinement_plan: RefinementPlan,
        started_at: float,
        reason: str,
    ) -> EnhancedResearchReport:
        """Create deterministic, refined output without an AI completion."""
        try:
            fallback_report = EnhancedResearchReport(
                base_report=report,
                executive_summary=refinement_plan.executive_summary,
                findings=refinement_plan.findings,
                appendix_findings=refinement_plan.appendix_findings,
                sections=(),
                synthesis_metadata=SynthesisMetadata(
                    provider="fallback",
                    model=None,
                    elapsed_ms=(perf_counter() - started_at) * 1000,
                    successful=True,
                    enhanced=False,
                    fallback=True,
                    reason=reason,
                    source_evidence=refinement_plan.source_evidence,
                ),
            )
        except ValidationError as exc:
            raise ReportSynthesisError(
                "Unable to construct a deterministic fallback report."
            ) from exc

        if fallback_report.base_report is not report:
            raise ReportSynthesisError(
                "EnhancedResearchReport must retain the original base report instance."
            )
        return fallback_report

    @staticmethod
    def _log_success(model: str, object_count: int, started_at: float) -> None:
        """Log safe success telemetry without report or source text."""
        logger.info(
            "Document synthesis completed | model=%s | knowledge_object_count=%d | "
            "elapsed_ms=%.2f | outcome=success",
            model,
            object_count,
            (perf_counter() - started_at) * 1000,
        )

    @staticmethod
    def _log_failure(model: str, object_count: int, started_at: float) -> None:
        """Log safe failure telemetry without report or source text."""
        logger.error(
            "Document synthesis completed | model=%s | knowledge_object_count=%d | "
            "elapsed_ms=%.2f | outcome=failure",
            model,
            object_count,
            (perf_counter() - started_at) * 1000,
        )

    @staticmethod
    def _log_fallback(reason: str, message: str, started_at: float) -> None:
        """Log one safe, structured warning for a deterministic fallback."""
        logger.warning(
            "Document synthesis fallback | provider=groq | fallback=true | "
            "reason=%s | message=%s | elapsed_ms=%.2f",
            reason,
            message,
            (perf_counter() - started_at) * 1000,
        )
