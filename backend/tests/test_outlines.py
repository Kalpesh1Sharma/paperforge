"""Evidence-aware outline persistence and approval-gate tests."""

import asyncio
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
import fitz
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app.api.dependencies import get_outline_service
from app.main import app
from app.models.parsed_document import ParsedDocument
from app.outlines import OutlineService
from app.reports import ReportGenerationSettings
from app.services.report_service import InvalidReportUploadError
from app.services.upload_service import UploadService


def _settings() -> ReportGenerationSettings:
    return ReportGenerationSettings.model_validate(
        {
            "schema_version": 2,
            "project_title": "Cloud systems",
            "research_domain": "Software engineering",
            "report_structure": {
                "preset": "technical",
                "sections": [
                    {"key": "abstract", "heading": "Abstract"},
                    {"key": "technical-analysis", "heading": "System Analysis"},
                ],
            },
            "visual_theme": {"template": "ieee-inspired-technical"},
            "outline_approval": {"approved": False, "proposal_id": None, "revision": 0},
            "publication": {"title": "Cloud Review", "author": "Researcher"},
        }
    )


def _document() -> ParsedDocument:
    text = (
        "The system architecture uses an API implementation and model. "
        "The methodology evaluates performance data and findings."
    )
    return ParsedDocument(
        filename="cloud.pdf",
        file_type="pdf",
        extracted_text=text,
        page_count=2,
        word_count=len(text.split()),
        character_count=len(text),
        metadata={},
    )


def test_outline_is_evidence_scored_persisted_and_explicitly_approved(tmp_path: Path) -> None:
    service = OutlineService(tmp_path, UploadService(tmp_path, 1_000_000))
    proposal = service._build(uuid4(), ("cloud.pdf",), (_document(),), _settings())
    service._save(proposal)

    technical = next(item for item in proposal.catalog if item.key == "technical-analysis")
    assert technical.evidence_count >= 5
    assert technical.source_count == 1
    with pytest.raises(InvalidReportUploadError, match="Approve"):
        service.assert_generation_allowed(_settings())

    sections = tuple(
        section.model_copy(update={"heading": "Architecture Assessment"})
        if section.key == "technical-analysis"
        else section
        for section in _settings().report_structure.sections
    )
    approved = service.approve(proposal.proposal_id, sections)
    allowed = _settings().model_copy(
        update={
            "report_structure": _settings().report_structure.model_copy(
                update={"sections": sections}
            ),
            "outline_approval": _settings().outline_approval.model_copy(
                update={
                    "approved": True,
                    "proposal_id": str(approved.proposal_id),
                    "revision": approved.revision,
                }
            ),
        }
    )
    service.assert_generation_allowed(allowed)
    assert service.get(proposal.proposal_id).status == "approved"


def test_generation_rejects_sections_changed_after_approval(tmp_path: Path) -> None:
    service = OutlineService(tmp_path, UploadService(tmp_path, 1_000_000))
    settings = _settings()
    proposal = service._build(uuid4(), ("cloud.pdf",), (_document(),), settings)
    service._save(proposal)
    approved = service.approve(proposal.proposal_id, settings.report_structure.sections)
    changed = settings.model_copy(
        update={
            "report_structure": settings.report_structure.model_copy(
                update={"sections": (settings.report_structure.sections[0],)}
            ),
            "outline_approval": settings.outline_approval.model_copy(
                update={"approved": True, "proposal_id": str(approved.proposal_id), "revision": approved.revision}
            ),
        }
    )
    with pytest.raises(InvalidReportUploadError, match="changed after approval"):
        service.assert_generation_allowed(changed)


def test_create_scans_real_pdf_and_removes_temporary_source_copy(tmp_path: Path) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "System architecture methodology performance evidence findings API implementation.",
    )
    payload = document.tobytes()
    document.close()
    service = OutlineService(tmp_path, UploadService(tmp_path, 1_000_000))
    upload = UploadFile(BytesIO(payload), filename="architecture.pdf")

    proposal = asyncio.run(service.create([upload], _settings()))

    assert proposal.status == "draft"
    assert proposal.source_filenames == ("architecture.pdf",)
    assert (tmp_path / "outline-proposals" / f"{proposal.proposal_id}.json").is_file()
    assert not (tmp_path / str(proposal.proposal_id)).exists()


def test_outline_api_creates_and_approves_an_edited_revision(tmp_path: Path) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Architecture API methodology findings and evidence.")
    payload = document.tobytes()
    document.close()
    service = OutlineService(tmp_path, UploadService(tmp_path, 1_000_000))
    app.dependency_overrides[get_outline_service] = lambda: service
    try:
        with TestClient(app) as client:
            created = client.post(
                "/reports/outlines",
                files=[("files", ("architecture.pdf", payload, "application/pdf"))],
                data={"settings": _settings().model_dump_json()},
            )
            assert created.status_code == 201
            proposal = created.json()
            assert proposal["status"] == "draft"
            edited = [
                {"key": "technical-analysis", "heading": "Architecture Review"},
                {"key": "abstract", "heading": "Synopsis"},
            ]
            approved = client.post(
                f"/reports/outlines/{proposal['proposal_id']}/approve",
                json={"sections": edited},
            )
            assert approved.status_code == 200
            assert approved.json()["revision"] == 2
            assert [item["heading"] for item in approved.json()["sections"]] == [
                "Architecture Review",
                "Synopsis",
            ]
    finally:
        app.dependency_overrides.clear()
