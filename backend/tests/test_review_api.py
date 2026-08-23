"""FastAPI boundary tests for the controlled review routes."""

from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_review_service
from app.integrations.superdocs.client import SuperDocsClient
from app.main import app
from app.models.review import PendingChange, ReviewState
from app.services.report_service import LocalReportStore
from app.services.review_service import ReviewService


def _state(report_id: UUID, *, status: str = "awaiting_approval", docx: bool = False) -> ReviewState:
    return ReviewState(
        report_id=report_id,
        session_id=f"paperforge-review-{report_id}",
        job_id="job-1",
        status=status,  # type: ignore[arg-type]
        pending_changes=(
            PendingChange(
                change_id="ch-1", operation="edit", chunk_id="chunk-1",
                old_html="<p>Before</p>", new_html="<p>After</p>", ai_explanation="Clearer.",
            ),
        ) if status == "awaiting_approval" else (),
        final_docx_available=docx,
    )


class _ReviewApiFake:
    def __init__(self, report_id: UUID, docx_path: Path) -> None:
        self.state = _state(report_id)
        self.calls: list[tuple[str, object]] = []
        self._docx_path = docx_path

    def start_review(self, report_id: UUID) -> ReviewState:
        self.calls.append(("start", report_id))
        return self.state

    def get_review(self, report_id: UUID) -> ReviewState:
        self.calls.append(("get", report_id))
        return self.state

    def approve(self, report_id: UUID, change_id: str) -> ReviewState:
        self.calls.append(("approve", change_id))
        return self.state

    def reject(self, report_id: UUID, change_id: str, feedback: str | None = None) -> ReviewState:
        self.calls.append(("reject", (change_id, feedback)))
        return self.state

    def docx_path(self, report_id: UUID) -> Path:
        self.calls.append(("docx", report_id))
        return self._docx_path


def test_review_routes_expose_exact_changes_and_do_not_poll_on_get(tmp_path: Path) -> None:
    report_id = uuid4()
    docx_path = tmp_path / "reviewed.docx"
    docx_path.write_bytes(b"PK\x03\x04")
    fake = _ReviewApiFake(report_id, docx_path)
    app.dependency_overrides[get_review_service] = lambda: fake
    try:
        with TestClient(app) as client:
            started = client.post(f"/reports/{report_id}/review")
            read = client.get(f"/reports/{report_id}/review")
            approved = client.post(f"/reports/{report_id}/review/approve", json={"change_id": "ch-1"})
            rejected = client.post(f"/reports/{report_id}/review/reject", json={"change_id": "ch-1", "feedback": "Keep it."})
    finally:
        app.dependency_overrides.clear()

    assert [response.status_code for response in (started, read, approved, rejected)] == [200, 200, 200, 200]
    assert started.json()["pending_changes"][0]["old_html"] == "<p>Before</p>"
    assert started.json()["pending_changes"][0]["new_html"] == "<p>After</p>"
    assert "machine_checks" not in started.text
    assert fake.calls == [
        ("start", report_id), ("get", report_id), ("approve", "ch-1"), ("reject", ("ch-1", "Keep it.")),
    ]


def test_missing_optional_superdocs_key_returns_safe_503_without_affecting_store(tmp_path: Path) -> None:
    report_id = uuid4()
    store = LocalReportStore(tmp_path / "reports")
    store.ensure_report_directory(report_id)
    store.write_json(report_id, "report.json", {"complete": True})
    store.write_text(report_id, "report.html", "<p>Stored report</p>")
    service = ReviewService(
        store=store,
        client=SuperDocsClient(api_key=None, base_url="https://api.superdocs.app"),
        poll_interval_seconds=0,
    )
    app.dependency_overrides[get_review_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(f"/reports/{report_id}/review")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "review_unavailable"
    assert "api_key" not in response.text.casefold()
    assert store.read_text(report_id, "report.html") == "<p>Stored report</p>"
