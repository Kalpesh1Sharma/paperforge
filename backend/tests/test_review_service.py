"""Offline workflow tests for explicit, verified SuperDocs human review."""

import io
import json
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.integrations.superdocs.exceptions import SuperDocsProtocolError, SuperDocsUnavailableError
from app.services.report_service import LocalReportStore
from app.services.review_service import ReviewService, ReviewVerificationError
from app.models.review import ReviewState


def _change(change_id: str = "ch-1", operation: str = "edit") -> dict[str, object]:
    return {
        "change_id": change_id, "operation": operation, "chunk_id": "chunk-1",
        "old_html": "<p>Original executive summary.</p>",
        "new_html": "<p>Clear revised executive summary.</p>",
        "ai_explanation": "Improves clarity.", "insert_after_chunk_id": None,
    }


def _docx(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"><w:body><w:p><w:r><w:t>"
            + text + "</w:t></w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


class _FakeClient:
    def __init__(self, jobs: list[dict[str, object]], docx: bytes | None = None) -> None:
        self.jobs = jobs
        self.start_calls: list[dict[str, str]] = []
        self.decisions: list[dict[str, object]] = []
        self.export_calls: list[dict[str, str]] = []
        self.get_calls: list[str] = []
        self.docx = docx or _docx("Clear revised executive summary.")

    def start_review(self, *, message: str, session_id: str, document_html: str) -> dict[str, object]:
        self.start_calls.append({"message": message, "session_id": session_id, "document_html": document_html})
        return {"job_id": "job-1", "session_id": session_id, "status": "pending"}

    def get_job(self, job_id: str) -> dict[str, object]:
        self.get_calls.append(job_id)
        assert job_id == "job-1"
        return self.jobs.pop(0)

    def decide_change(self, **payload: object) -> dict[str, object]:
        self.decisions.append(payload)
        return {"status": "accepted"}

    def export_docx(self, *, session_id: str, filename: str) -> bytes:
        self.export_calls.append({"session_id": session_id, "filename": filename})
        return self.docx


def _service(tmp_path: Path, client: _FakeClient, report_id: UUID | None = None) -> tuple[ReviewService, LocalReportStore, UUID]:
    store = LocalReportStore(tmp_path / "reports")
    active_id = report_id or uuid4()
    store.ensure_report_directory(active_id)
    store.write_json(active_id, "report.json", {"complete": True})
    store.write_text(active_id, "report.html", "<html><body>Stored report HTML</body></html>")
    return ReviewService(store=store, client=client, poll_interval_seconds=0, max_wait_seconds=1), store, active_id


def test_start_review_polls_persists_exact_pending_changes_and_is_idempotent(tmp_path: Path) -> None:
    client = _FakeClient([
        {"status": "pending", "metadata": {}},
        {"status": "in_progress", "metadata": {}},
        {"status": "awaiting_approval", "metadata": {"pending_changes": json.dumps(json.dumps([_change()]))}},
    ])
    service, store, report_id = _service(tmp_path, client)
    state = service.start_review(report_id)
    again = service.start_review(report_id)

    assert state.status == "awaiting_approval" and state.pending_changes[0].change_id == "ch-1"
    assert again == state and len(client.start_calls) == 1
    assert client.start_calls[0]["session_id"] == f"paperforge-review-{report_id}"
    assert client.start_calls[0]["document_html"] == "<html><body>Stored report HTML</body></html>"
    review_json = store.read_text(report_id, "review.json")
    assert "test-key" not in review_json and "Stored report HTML" not in review_json
    assert service.get_review(report_id) == state


def test_live_additive_provider_metadata_is_normalized_without_persistence(tmp_path: Path) -> None:
    live_change = {
        **_change(),
        "document_id": "doc_primary",
        "insert_before_chunk_id": None,
        "machine_checks": {
            "claims": {"supported": True}, "resolved": {}, "words_new": 1745,
            "words_old": 1742, "blocks_new": 1, "blocks_old": 1,
            "kept_chars_ratio": 1.0,
        },
    }
    client = _FakeClient([{"status": "awaiting_approval", "metadata": {"pending_changes": [live_change]}}])
    service, store, report_id = _service(tmp_path, client)
    state = service.start_review(report_id)

    change = state.pending_changes[0]
    assert change.document_id == "doc_primary"
    assert change.old_html == live_change["old_html"]
    assert change.new_html == live_change["new_html"]
    serialized = store.read_text(report_id, "review.json")
    assert "machine_checks" not in serialized
    assert "words_new" not in serialized


def test_processing_state_recovers_existing_provider_job_without_starting_another(tmp_path: Path) -> None:
    client = _FakeClient([{"status": "awaiting_approval", "metadata": {"pending_changes": [_change()]}}])
    service, store, report_id = _service(tmp_path, client)
    existing = ReviewState(
        report_id=report_id,
        session_id="paperforge-review-existing",
        job_id="job-1",
        status="processing",
    )
    store.write_json(report_id, "review.json", existing.model_dump(mode="json"))

    recovered = service.start_review(report_id)
    repeated = service.start_review(report_id)

    assert recovered.status == "awaiting_approval"
    assert recovered.session_id == "paperforge-review-existing"
    assert recovered.job_id == "job-1"
    assert recovered.pending_changes[0].change_id == "ch-1"
    assert not client.start_calls
    assert client.get_calls == ["job-1"]
    assert repeated == recovered and client.get_calls == ["job-1"]


def test_continue_prompt_never_becomes_a_pending_change_or_decision(tmp_path: Path) -> None:
    client = _FakeClient([{"status": "awaiting_approval", "metadata": {"awaiting_kind": "continue_prompt"}}])
    service, _, report_id = _service(tmp_path, client)
    state = service.start_review(report_id)
    assert state.status == "needs_attention" and not state.pending_changes
    assert not client.decisions


def test_approve_only_one_pending_change_then_exports_and_verifies(tmp_path: Path) -> None:
    first, second = _change("ch-1"), _change("ch-2")
    client = _FakeClient([
        {"status": "awaiting_approval", "metadata": {"pending_changes": [first, second]}},
        {"status": "awaiting_approval", "metadata": {"pending_changes": [second]}},
        {"status": "completed", "metadata": {}},
    ])
    service, _, report_id = _service(tmp_path, client)
    service.start_review(report_id)
    remaining = service.approve(report_id, "ch-1")
    assert remaining.status == "awaiting_approval" and [item.change_id for item in remaining.pending_changes] == ["ch-2"]
    assert client.decisions == [{"session_id": f"paperforge-review-{report_id}", "job_id": "job-1", "change_id": "ch-1", "approved": True, "feedback": None}]
    completed = service.approve(report_id, "ch-2")
    assert completed.status == "completed" and completed.final_docx_available
    assert client.export_calls == [{"session_id": f"paperforge-review-{report_id}", "filename": f"paperforge-{report_id}-reviewed"}]
    assert service.docx_path(report_id).read_bytes().startswith(b"PK")


def test_rejection_with_feedback_can_require_a_new_explicit_round(tmp_path: Path) -> None:
    client = _FakeClient([
        {"status": "awaiting_approval", "metadata": {"pending_changes": [_change()]}},
        {"status": "awaiting_approval", "metadata": {"pending_changes": [_change("ch-2")]}},
    ])
    service, _, report_id = _service(tmp_path, client)
    service.start_review(report_id)
    state = service.reject(report_id, "ch-1", "Keep the original wording.")
    assert state.status == "awaiting_approval" and state.pending_changes[0].change_id == "ch-2"
    assert state.rejected_changes[0].change_id == "ch-1"
    assert client.decisions[0]["approved"] is False and client.decisions[0]["feedback"] == "Keep the original wording."


@pytest.mark.parametrize("operation, docx_text", [("create", "Clear revised executive summary."), ("delete", "Different document text.")])
def test_docx_verification_supports_create_and_delete(tmp_path: Path, operation: str, docx_text: str) -> None:
    change = _change(operation=operation)
    client = _FakeClient([
        {"status": "awaiting_approval", "metadata": {"pending_changes": [change]}},
        {"status": "completed", "metadata": {}},
    ], _docx(docx_text))
    service, _, report_id = _service(tmp_path, client)
    service.start_review(report_id)
    assert service.approve(report_id, "ch-1").final_docx_available


def test_invalid_pending_changes_and_missing_approved_text_fail_safely(tmp_path: Path) -> None:
    malformed = _FakeClient([{"status": "awaiting_approval", "metadata": {"pending_changes": "not json"}}])
    service, _, report_id = _service(tmp_path, malformed)
    with pytest.raises(SuperDocsProtocolError):
        service.start_review(report_id)

    bad_export = _FakeClient([
        {"status": "awaiting_approval", "metadata": {"pending_changes": [_change()]}},
        {"status": "completed", "metadata": {}},
    ], _docx("The old text remains."))
    service, _, report_id = _service(tmp_path / "export", bad_export)
    service.start_review(report_id)
    with pytest.raises(ReviewVerificationError):
        service.approve(report_id, "ch-1")
    assert service.get_review(report_id).status == "failed"


def test_unknown_decision_and_timeout_are_bounded(tmp_path: Path) -> None:
    client = _FakeClient([{"status": "awaiting_approval", "metadata": {"pending_changes": [_change()]}}])
    service, _, report_id = _service(tmp_path, client)
    service.start_review(report_id)
    with pytest.raises(Exception, match="no longer pending"):
        service.approve(report_id, "unknown")

    timeout = _FakeClient([{"status": "pending", "metadata": {}}])
    service, _, report_id = _service(tmp_path / "timeout", timeout)
    service._max_wait_seconds = 0  # test-only bounded monotonic timeout
    with pytest.raises(SuperDocsUnavailableError):
        service.start_review(report_id)
