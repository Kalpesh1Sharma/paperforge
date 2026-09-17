"""SQLite persistence and HTTP coverage for workspace projects."""

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_project_service
from app.main import app
from app.models.parsed_document import ParsedDocument
from app.projects import ProjectService, SQLiteProjectStore


def _service(tmp_path: Path) -> ProjectService:
    report_root = tmp_path / "reports"
    return ProjectService(
        SQLiteProjectStore(report_root / "paperforge.db"), report_root
    )


def _document(filename: str = "research.pdf") -> ParsedDocument:
    return ParsedDocument(
        filename=filename,
        file_type="pdf",
        extracted_text="Grounded research evidence.",
        page_count=2,
        word_count=3,
        character_count=29,
        metadata={},
    )


def test_projects_persist_across_service_instances(tmp_path: Path) -> None:
    first_service = _service(tmp_path)
    project = first_service.create("  Evidence   Review  ")
    report_id = uuid4()
    ready = first_service.attach_report(
        report_id,
        (_document(),),
        ("json", "html", "pdf"),
        project_id=project.id,
    )

    second_service = _service(tmp_path)
    restored = second_service.get(project.id)

    assert restored.title == "Evidence Review"
    assert restored.report_id == report_id
    assert restored.status == "ready"
    assert restored.sources[0].filename == "research.pdf"
    assert restored.available_formats == ("json", "html", "pdf")


def test_existing_report_directories_are_backfilled_once(tmp_path: Path) -> None:
    report_id = uuid4()
    report_directory = tmp_path / "reports" / str(report_id)
    report_directory.mkdir(parents=True)
    (report_directory / "report.json").write_text("{}", encoding="utf-8")
    (report_directory / "metadata.json").write_text(
        json.dumps(
            {
                "report_id": str(report_id),
                "status": "completed",
                "available_formats": ["json", "html", "pdf"],
                "document": {
                    "filename": "existing_report.pdf",
                    "file_type": "pdf",
                    "page_count": 4,
                    "word_count": 800,
                    "character_count": 4200,
                },
                "generation": {},
            }
        ),
        encoding="utf-8",
    )

    restored = _service(tmp_path).get(report_id)

    assert restored.report_id == report_id
    assert restored.title == "Existing Report"
    assert restored.sources[0].page_count == 4


def test_project_crud_api_uses_sqlite_state(tmp_path: Path) -> None:
    service = _service(tmp_path)
    app.dependency_overrides[get_project_service] = lambda: service
    try:
        with TestClient(app) as client:
            created = client.post("/projects", json={"title": "Research workspace"})
            project_id = created.json()["id"]
            listed = client.get("/projects")
            renamed = client.patch(
                f"/projects/{project_id}", json={"title": "AI Policy Review"}
            )
            opened = client.get(f"/projects/{project_id}")
            deleted = client.delete(f"/projects/{project_id}")
            missing = client.get(f"/projects/{project_id}")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert created.json()["status"] == "draft"
    assert [item["id"] for item in listed.json()] == [project_id]
    assert renamed.status_code == 200
    assert opened.json()["title"] == "AI Policy Review"
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "project_not_found"


def test_project_api_rejects_blank_titles_and_malformed_ids(tmp_path: Path) -> None:
    service = _service(tmp_path)
    app.dependency_overrides[get_project_service] = lambda: service
    try:
        with TestClient(app) as client:
            blank = client.post("/projects", json={"title": "   "})
            malformed = client.get("/projects/not-a-uuid")
    finally:
        app.dependency_overrides.clear()

    assert blank.status_code == 400
    assert blank.json()["error"]["code"] == "invalid_project"
    assert malformed.status_code == 422


def test_deleting_ready_project_removes_report_files(tmp_path: Path) -> None:
    service = _service(tmp_path)
    report_id = uuid4()
    report_directory = tmp_path / "reports" / str(report_id)
    report_directory.mkdir(parents=True)
    (report_directory / "report.pdf").write_bytes(b"%PDF")
    project = service.attach_report(
        report_id,
        (_document(),),
        ("json", "html", "pdf", "docx"),
    )

    service.delete(project.id)

    assert not report_directory.exists()
    assert service.list() == ()
