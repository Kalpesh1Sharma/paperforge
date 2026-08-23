"""Controlled, local-state-backed SuperDocs human review orchestration."""

from __future__ import annotations

import json
import io
import re
import time
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from collections.abc import Mapping
from typing import Callable, Protocol
from uuid import UUID
from xml.etree import ElementTree

from pydantic import ValidationError

from app.integrations.superdocs.exceptions import (
    SuperDocsNotConfiguredError,
    SuperDocsProtocolError,
    SuperDocsUnavailableError,
)
from app.models.review import PendingChange, ReviewState
from app.services.report_service import LocalReportStore, ReportNotFoundError, ReportStorageError


REVIEW_MESSAGE = (
    "Edit only the Executive Summary section of this research report. Improve "
    "clarity and concision while preserving every factual claim, number, metric, "
    "source reference, and meaning. Do not modify any other section. Make one "
    "targeted revision only. Do not add unsupported facts."
)
_PENDING_CHANGE_FIELDS = frozenset(
    {
        "change_id",
        "operation",
        "chunk_id",
        "document_id",
        "old_html",
        "new_html",
        "ai_explanation",
        "insert_after_chunk_id",
        "insert_before_chunk_id",
    }
)


class ReviewNotFoundError(RuntimeError):
    """Raised when no local review state exists for a completed report."""


class ReviewAlreadyExistsError(RuntimeError):
    """Reserved for callers that require a new review instead of idempotency."""


class ReviewInvalidStateError(RuntimeError):
    """Raised when a human decision cannot apply to local pending state."""


class ReviewVerificationError(RuntimeError):
    """Raised when the exported DOCX lacks approved human-reviewed changes."""


class _SuperDocsReviewClient(Protocol):
    def start_review(self, *, message: str, session_id: str, document_html: str) -> dict[str, object]: ...
    def get_job(self, job_id: str) -> dict[str, object]: ...
    def decide_change(self, *, session_id: str, job_id: str, change_id: str, approved: bool, feedback: str | None = None) -> dict[str, object]: ...
    def export_docx(self, *, session_id: str, filename: str) -> bytes: ...


class ReviewService:
    """Perform the finite, explicit-approval review workflow for stored reports."""

    def __init__(
        self,
        *,
        store: LocalReportStore,
        client: _SuperDocsReviewClient,
        poll_interval_seconds: float = 2.0,
        max_wait_seconds: float = 120.0,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._store = store
        self._client = client
        self._poll_interval_seconds = max(0.0, poll_interval_seconds)
        self._max_wait_seconds = max(0.0, max_wait_seconds)
        self._monotonic = monotonic
        self._sleep = sleep

    def start_review(self, report_id: UUID) -> ReviewState:
        """Start one idempotent, approval-gated review from persisted HTML."""
        self._require_completed_report(report_id)
        existing = self._read_optional_state(report_id)
        if existing is not None:
            if existing.status == "processing" and existing.job_id:
                # A prior start obtained a provider job but did not reach its
                # first terminal poll. Recover that paid job; never start one.
                return self._poll(existing)
            return existing
        session_id = f"paperforge-review-{report_id}"
        state = ReviewState(
            report_id=report_id, session_id=session_id, status="processing"
        )
        self._write_state(state)
        document_html = self._store.read_text(report_id, "report.html")
        try:
            response = self._client.start_review(
                message=REVIEW_MESSAGE,
                session_id=session_id,
                document_html=document_html,
            )
        except SuperDocsNotConfiguredError:
            # No provider request occurred, so do not turn missing optional
            # configuration into a durable state that blocks a later retry.
            self._store.artifact_path(report_id, "review.json").unlink(missing_ok=True)
            raise
        job_id = self._required_text(response, "job_id")
        if self._required_text(response, "session_id") != session_id:
            raise SuperDocsProtocolError("SuperDocs returned an invalid review session.")
        self._required_text(response, "status")
        return self._poll(state.model_copy(update={"job_id": job_id}))

    def get_review(self, report_id: UUID) -> ReviewState:
        """Read only local persisted review state; never poll the provider."""
        self._require_completed_report(report_id)
        state = self._read_optional_state(report_id)
        if state is None:
            raise ReviewNotFoundError("Review was not found.")
        return state

    def approve(self, report_id: UUID, change_id: str) -> ReviewState:
        """Submit one explicit approval and then poll the same provider job."""
        return self._decide(report_id, change_id, approved=True, feedback=None)

    def reject(self, report_id: UUID, change_id: str, feedback: str | None = None) -> ReviewState:
        """Submit one explicit rejection without implicitly deciding other changes."""
        return self._decide(report_id, change_id, approved=False, feedback=feedback)

    def docx_path(self, report_id: UUID) -> Path:
        """Return a final DOCX only after successful export and verification."""
        state = self.get_review(report_id)
        if state.status != "completed" or not state.final_docx_available:
            raise ReviewNotFoundError("Reviewed DOCX is not available.")
        return self._store.file_path(report_id, "reviewed_report.docx")

    def _decide(
        self, report_id: UUID, change_id: str, *, approved: bool, feedback: str | None
    ) -> ReviewState:
        state = self.get_review(report_id)
        if state.status != "awaiting_approval" or not state.job_id:
            raise ReviewInvalidStateError("The review is not awaiting a decision.")
        pending = next((item for item in state.pending_changes if item.change_id == change_id), None)
        if pending is None:
            raise ReviewInvalidStateError("The proposed change is no longer pending.")
        self._client.decide_change(
            session_id=state.session_id,
            job_id=state.job_id,
            change_id=change_id,
            approved=approved,
            feedback=feedback if not approved else None,
        )
        remaining = tuple(item for item in state.pending_changes if item != pending)
        updated = state.model_copy(
            update={
                "status": "processing",
                "pending_changes": remaining,
                "approved_changes": state.approved_changes + ((pending,) if approved else ()),
                "rejected_changes": state.rejected_changes + ((pending,) if not approved else ()),
            }
        )
        return self._poll(updated)

    def _poll(self, state: ReviewState) -> ReviewState:
        """Poll with a monotonic bounded wait and persist every safe terminal state."""
        if not state.job_id:
            raise SuperDocsProtocolError("SuperDocs did not provide a review job ID.")
        self._write_state(state)
        started = self._monotonic()
        while True:
            payload = self._client.get_job(state.job_id)
            provider_status = self._required_text(payload, "status")
            metadata = payload.get("metadata", {})
            if not isinstance(metadata, dict):
                raise SuperDocsProtocolError("SuperDocs returned invalid job metadata.")
            if provider_status in {"pending", "in_progress"}:
                if self._monotonic() - started >= self._max_wait_seconds:
                    self._write_state(state)
                    raise SuperDocsUnavailableError("SuperDocs review polling timed out.")
                if self._poll_interval_seconds:
                    self._sleep(self._poll_interval_seconds)
                continue
            if provider_status == "awaiting_approval":
                if metadata.get("awaiting_kind") == "continue_prompt":
                    return self._persist(state.model_copy(update={
                        "status": "needs_attention", "pending_changes": ()
                    }))
                changes = self._decode_pending_changes(metadata.get("pending_changes"))
                return self._persist(state.model_copy(update={
                    "status": "awaiting_approval", "pending_changes": changes
                }))
            if provider_status == "completed":
                return self._complete(state)
            if provider_status in {"failed", "cancelled"}:
                return self._persist(state.model_copy(update={
                    "status": provider_status, "pending_changes": ()
                }))
            raise SuperDocsProtocolError("SuperDocs returned an unknown review status.")

    def _complete(self, state: ReviewState) -> ReviewState:
        """Export and verify only after at least one explicit human decision."""
        if not state.approved_changes and not state.rejected_changes:
            return self._persist(state.model_copy(update={
                "status": "completed", "pending_changes": ()
            }))
        docx = self._client.export_docx(
            session_id=state.session_id,
            filename=f"paperforge-{state.report_id}-reviewed",
        )
        self._store.write_bytes(state.report_id, "reviewed_report.docx", docx)
        try:
            self._verify_docx(docx, state.approved_changes)
        except ReviewVerificationError:
            self._persist(state.model_copy(update={
                "status": "failed", "pending_changes": (), "final_docx_available": False
            }))
            raise
        return self._persist(state.model_copy(update={
            "status": "completed", "pending_changes": (), "final_docx_available": True
        }))

    def _require_completed_report(self, report_id: UUID) -> None:
        if not self._store.has_completed_report(report_id):
            raise ReportNotFoundError("Report was not found.")

    def _read_optional_state(self, report_id: UUID) -> ReviewState | None:
        path = self._store.artifact_path(report_id, "review.json")
        if not path.is_file():
            return None
        try:
            return ReviewState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise ReportStorageError("Stored review state is invalid.") from exc

    def _write_state(self, state: ReviewState) -> None:
        self._store.write_json(
            state.report_id, "review.json", state.model_dump(mode="json", warnings="error")
        )

    def _persist(self, state: ReviewState) -> ReviewState:
        self._write_state(state)
        return state

    @staticmethod
    def _required_text(payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise SuperDocsProtocolError("SuperDocs returned an invalid review response.")
        return value

    @staticmethod
    def _decode_pending_changes(value: object) -> tuple[PendingChange, ...]:
        """Decode at most twice, then strictly validate the provider's changes."""
        decoded = value
        for _ in range(2):
            if not isinstance(decoded, str):
                break
            try:
                decoded = json.loads(decoded)
            except json.JSONDecodeError as exc:
                raise SuperDocsProtocolError("SuperDocs returned invalid pending changes.") from exc
        if not isinstance(decoded, list):
            raise SuperDocsProtocolError("SuperDocs returned invalid pending changes.")
        try:
            changes = tuple(
                PendingChange.model_validate(
                    ReviewService._normalize_pending_change(item)
                )
                for item in decoded
            )
        except ValidationError as exc:
            raise SuperDocsProtocolError("SuperDocs returned invalid pending changes.") from exc
        if not changes:
            raise SuperDocsProtocolError("SuperDocs did not provide a proposed change.")
        return changes

    @staticmethod
    def _normalize_pending_change(value: object) -> dict[str, object]:
        """Project provider changes onto the strict PaperForge-owned contract."""
        if not isinstance(value, Mapping):
            raise SuperDocsProtocolError("SuperDocs returned invalid pending changes.")
        # Deliberately discard diagnostics and future provider-only additions.
        # Strict validation below still rejects missing or malformed core fields.
        return {
            key: value[key]
            for key in _PENDING_CHANGE_FIELDS
            if key in value
        }

    @classmethod
    def _verify_docx(cls, docx: bytes, approved_changes: tuple[PendingChange, ...]) -> None:
        document_text = cls._normalized_docx_text(docx)
        for change in approved_changes:
            old_text = cls._normalized_html_text(change.old_html)
            new_text = cls._normalized_html_text(change.new_html)
            if change.operation in {"edit", "create"}:
                if not new_text or new_text not in document_text:
                    raise ReviewVerificationError("The approved change was not found in the DOCX export.")
            elif change.operation == "delete" and old_text and old_text in document_text:
                raise ReviewVerificationError("The deleted change remains in the DOCX export.")

    @staticmethod
    def _normalized_docx_text(docx: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(docx)) as archive:
                document = archive.read("word/document.xml")
            root = ElementTree.fromstring(document)
        except (KeyError, OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise ReviewVerificationError("The DOCX export could not be verified.") from exc
        text = " ".join(node.text or "" for node in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
        return ReviewService._normalize_text(text)

    @staticmethod
    def _normalized_html_text(value: str | None) -> str:
        if value is None:
            return ""
        parser = _TextParser()
        parser.feed(value)
        parser.close()
        return ReviewService._normalize_text(" ".join(parser.parts))

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()


class _TextParser(HTMLParser):
    """Small stdlib-only HTML-to-text helper for DOCX verification."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
