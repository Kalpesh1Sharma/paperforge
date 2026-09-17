"""Integration coverage for the synchronous production FastAPI service."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_paperforge_service
from app.main import app
from app.models.parsed_document import ParsedDocument
from app.models.document_chunk import DocumentChunk
from app.projects import ProjectService, SQLiteProjectStore
from app.reports import (
    EnhancedResearchReport,
    Finding,
    HTMLRenderer,
    MarkdownRenderer,
    ReportComposer,
    ReportRenderingError,
    ReportMode,
    ResearchReport,
    SynthesisMetadata,
    SynthesisSourceEvidence,
)
from app.services.pipeline_service import (
    MultiDocumentPipelineArtifacts,
    PipelineArtifacts,
    ProviderRateLimitedError,
)
from app.services.report_service import (
    LocalReportStore,
    PaperForgeService,
    StagedMultiReport,
    StagedReport,
)
from app.services.upload_service import UploadService


class _DeterministicPipelineService:
    """Local pipeline replacement that preserves the real service boundary."""

    def __init__(self, *, fallback: bool = False) -> None:
        self.calls: list[Path] = []
        self.many_calls: list[tuple[tuple[Path, ...], tuple[str, ...]]] = []
        self._fallback = fallback
        self.modes: list[ReportMode | None] = []

    def process(
        self,
        input_path: Path,
        *,
        mode: ReportMode | None = None,
        progress: object | None = None,
    ) -> PipelineArtifacts:
        del progress
        self.calls.append(input_path)
        self.modes.append(mode)
        source_text = "PaperForge documents deterministic report generation."
        source_document = ParsedDocument(
            filename=input_path.name,
            file_type="pdf",
            extracted_text=source_text,
            page_count=1,
            word_count=5,
            character_count=len(source_text),
            metadata={},
        )
        research_report = ResearchReport(
            title="Research Report",
            executive_summary="The document describes deterministic reporting.",
            findings=(),
            important_entities=(),
            important_definitions=(),
            important_metrics=(),
            timeline=(),
            references=(),
            sections=(),
        )
        enhanced_report = EnhancedResearchReport(
            base_report=research_report,
            executive_summary="The document describes deterministic reporting.",
            findings=(),
            appendix_findings=(),
            sections=(),
            synthesis_metadata=SynthesisMetadata(
                provider="fallback" if self._fallback else "groq",
                model=None if self._fallback else "test-model",
                elapsed_ms=1.0,
                successful=True,
                fallback=self._fallback,
                enhanced=not self._fallback,
                reason="rate_limit" if self._fallback else None,
                source_evidence=(
                    SynthesisSourceEvidence(
                        chunk_id=uuid4(),
                        confidence=0.5,
                        references=(),
                    ),
                )
                if self._fallback
                else (),
            ),
        )
        presentation = ReportComposer(mode=mode or ReportMode.PROFESSIONAL).compose(
            enhanced_report,
            source_document=source_document,
        )
        return PipelineArtifacts(
            source_document=source_document,
            chunks=(),
            knowledge_objects=(),
            research_report=research_report,
            enhanced_report=enhanced_report,
            presentation=presentation,
        )

    def process_many(
        self,
        input_paths: tuple[Path, ...],
        source_filenames: tuple[str, ...],
        *,
        mode: ReportMode | None = None,
        progress: object | None = None,
    ) -> MultiDocumentPipelineArtifacts:
        del progress
        self.many_calls.append((input_paths, source_filenames))
        self.modes.append(mode)
        documents = tuple(
            ParsedDocument(
                filename=filename,
                file_type="pdf",
                extracted_text=f"Evidence from {filename}.",
                page_count=1,
                word_count=3,
                character_count=len(f"Evidence from {filename}."),
                metadata={},
            )
            for filename in source_filenames
        )
        chunks = tuple(
            DocumentChunk(
                chunk_id=uuid4(), document_filename=document.filename,
                chunk_index=0, text=document.extracted_text, start_char=0,
                end_char=len(document.extracted_text), word_count=document.word_count,
                character_count=document.character_count, metadata={},
            )
            for document in documents
        )
        research_report = ResearchReport(
            title="Combined Research Report", executive_summary="Combined evidence.",
            findings=(Finding(title="Combined finding", description="Evidence spans the supplied documents.", supporting_chunk_ids=tuple(chunk.chunk_id for chunk in chunks)),),
        )
        enhanced_report = EnhancedResearchReport(
            base_report=research_report, executive_summary="Combined evidence.",
            findings=research_report.findings, appendix_findings=(), sections=(),
            synthesis_metadata=SynthesisMetadata(
                provider="groq", model="test-model", elapsed_ms=1.0, successful=True,
                source_evidence=tuple(SynthesisSourceEvidence(chunk_id=chunk.chunk_id, confidence=0.5, references=()) for chunk in chunks),
            ),
        )
        presentation = ReportComposer(mode=mode or ReportMode.PROFESSIONAL).compose(
            enhanced_report, source_documents=documents, source_chunks=chunks
        )
        return MultiDocumentPipelineArtifacts(
            source_documents=documents, chunks=chunks, knowledge_objects=(),
            research_report=research_report, enhanced_report=enhanced_report,
            presentation=presentation,
        )


class _FakePDFRenderer:
    """Write a minimal test artifact while avoiding a real Chromium dependency."""

    def render_presentation(self, presentation: object, output_path: Path) -> Path:
        del presentation
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"%PDF-1.7\nPaperForge test PDF\n")
        return output_path.resolve()


class _LoopSensitivePDFRenderer:
    """Fail if a synchronous renderer is invoked from an asyncio event loop."""

    def __init__(self) -> None:
        self.executed_outside_event_loop = False

    def render_presentation(self, presentation: object, output_path: Path) -> Path:
        del presentation
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.executed_outside_event_loop = True
        else:
            raise ReportRenderingError(
                "Synchronous PDF renderer executed inside the asyncio event loop."
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"%PDF-1.7\nPaperForge test PDF\n")
        return output_path.resolve()


class _RateLimitedService:
    """Minimal dependency replacement used to verify API error translation."""

    async def create_report(self, uploaded_file: object) -> object:
        del uploaded_file
        raise ProviderRateLimitedError("The knowledge provider is currently rate limited.")


def _service(
    tmp_path: Path,
    *,
    fallback: bool = False,
    pdf_renderer: object | None = None,
) -> tuple[PaperForgeService, _DeterministicPipelineService]:
    """Create a real report service around deterministic integration doubles."""
    store = LocalReportStore(tmp_path / "reports")
    pipeline = _DeterministicPipelineService(fallback=fallback)
    service = PaperForgeService(
        store=store,
        pipeline_service=pipeline,  # type: ignore[arg-type]
        upload_service=UploadService(
            upload_dir=store.root_dir,
            max_upload_size_bytes=1024 * 1024,
        ),
        markdown_renderer=MarkdownRenderer(),
        html_renderer=HTMLRenderer(),
        pdf_renderer=pdf_renderer or _FakePDFRenderer(),  # type: ignore[arg-type]
    )
    return service, pipeline


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Inject a filesystem-isolated service into the application dependency graph."""
    service, _ = _service(tmp_path)
    app.dependency_overrides[get_paperforge_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_report(client: TestClient) -> UUID:
    """Submit one valid multipart PDF and return its generated UUID."""
    response = client.post(
        "/reports",
        files={"file": ("research.pdf", b"%PDF-1.7\n", "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["report_id"])


def _create_multi_report(client: TestClient) -> UUID:
    response = client.post(
        "/reports/multi",
        files=[
            ("files", ("alpha.pdf", b"%PDF-1.7\n", "application/pdf")),
            ("files", ("beta.pdf", b"%PDF-1.7\n", "application/pdf")),
        ],
    )
    assert response.status_code == 201, response.text
    assert [item["filename"] for item in response.json()["documents"]] == ["alpha.pdf", "beta.pdf"]
    return UUID(response.json()["report_id"])


def test_health_reports_and_all_persisted_formats(client: TestClient) -> None:
    """One upload yields stable JSON, HTML, PDF, Markdown, and metadata artifacts."""
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert health.json()["ready"] is True
    assert health.headers["x-request-id"]

    report_id = _create_report(client)
    report = client.get(f"/reports/{report_id}")
    html = client.get(f"/reports/{report_id}/html")
    pdf = client.get(f"/reports/{report_id}/pdf")
    docx = client.get(f"/reports/{report_id}/editable-docx")
    markdown = client.get(f"/reports/{report_id}/markdown")
    metadata = client.get(f"/reports/{report_id}/metadata")

    assert report.status_code == 200
    assert report.json()["cover"]["filename"] == "research.pdf"
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in html.text
    assert pdf.status_code == 200 and pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF")
    assert docx.status_code == 200
    assert docx.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert docx.content.startswith(b"PK")
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert metadata.status_code == 200
    assert metadata.json()["document"]["page_count"] == 1
    assert metadata.json()["generation"]["provider"] == "groq"

    assert client.get(f"/reports/{report_id}").json() == report.json()


def test_upload_creates_required_local_artifacts_and_uses_injected_pipeline(
    tmp_path: Path,
) -> None:
    """The API uses injected collaborators and persists the documented store layout."""
    service, pipeline = _service(tmp_path)
    app.dependency_overrides[get_paperforge_service] = lambda: service
    try:
        with TestClient(app) as client:
            report_id = _create_report(client)
    finally:
        app.dependency_overrides.clear()

    report_directory = tmp_path / "reports" / str(report_id)
    assert pipeline.calls == [report_directory / "research.pdf"]
    assert {
        path.name for path in report_directory.iterdir()
    } >= {"input.pdf", "report.json", "report.html", "report.md", "report.pdf", "report.docx", "metadata.json"}
    project = ProjectService(
        SQLiteProjectStore(tmp_path / "reports" / "paperforge.db"),
        tmp_path / "reports",
    ).get(report_id)
    assert project.report_id == report_id
    assert project.sources[0].filename == "research.pdf"


def test_wizard_settings_control_structure_cover_metadata_and_project(
    tmp_path: Path,
) -> None:
    service, pipeline = _service(tmp_path)
    app.dependency_overrides[get_paperforge_service] = lambda: service
    settings = {
        "schema_version": 2,
        "project_title": "AI Governance Workspace",
        "research_domain": "Artificial Intelligence Governance",
        "purpose": "Brief an academic review panel.",
        "report_structure": {
            "preset": "technical",
            "sections": [
                {"key": "executive-summary", "heading": "Decision Summary"},
                {"key": "document-overview", "heading": "Evidence Scope"},
            ],
        },
        "content": {"tone": "academic", "audience": "Review panel", "language": "en"},
        "visual_theme": {"template": "editorial", "page_size": "A4", "density": "comfortable", "accent_color": None},
        "citations": {"style": "apa", "include_bibliography": True},
        "publication": {
            "title": "Responsible AI in Public Research",
            "subtitle": "Institutional evidence review",
            "author": "Kalpesh Sharma",
            "organisation": "PaperForge Lab",
            "university": "MNIT Jaipur",
            "department": "Computer Science",
            "publication_type": "Academic report",
        },
    }
    try:
        with TestClient(app) as client:
            response = client.post(
                "/reports",
                files={"file": ("research.pdf", b"%PDF-1.7\n", "application/pdf")},
                data={"settings": json.dumps(settings)},
            )
            report_id = UUID(response.json()["report_id"])
            report = client.get(f"/reports/{report_id}").json()
            metadata = client.get(f"/reports/{report_id}/metadata").json()
            html = client.get(f"/reports/{report_id}/html").text
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert pipeline.modes == [ReportMode.TECHNICAL]
    assert report["mode"] == "technical"
    assert report["template_key"] == "editorial"
    assert report["cover"]["title"] == settings["publication"]["title"]
    assert report["cover"]["author"] == "Kalpesh Sharma"
    assert report["cover"]["university"] == "MNIT Jaipur"
    assert report["citation_style"] == "apa"
    assert [(section["key"], section["heading"]) for section in report["sections"]] == [
        ("executive-summary", "Decision Summary"),
        ("document-overview", "Evidence Scope"),
    ]
    overview = next(
        section for section in report["sections"]
        if section["key"] == "document-overview"
    )
    assert any(settings["research_domain"] in paragraph for paragraph in overview["intro"])
    assert not any("General Research" in paragraph for paragraph in overview["intro"])
    assert metadata["settings"]["schema_version"] == 2
    assert metadata["settings"]["report_structure"]["preset"] == "technical"
    assert metadata["settings"]["visual_theme"]["template"] == "editorial"
    assert metadata["settings"]["publication"] == {
        "title": "Responsible AI in Public Research",
        "subtitle": "Institutional evidence review",
        "author": "Kalpesh Sharma",
        "organisation": "PaperForge Lab",
        "university": "MNIT Jaipur",
        "department": "Computer Science",
        "publication_type": "Academic report",
    }
    assert "Kalpesh Sharma" in html and "MNIT Jaipur" in html
    assert "Institutional evidence review" in html
    assert "Citation style" in html and "APA" in html
    assert "Prepared by Kalpesh Sharma." in html
    assert service._project_service.get(report_id).title == "AI Governance Workspace"


def test_invalid_wizard_settings_are_rejected_before_generation(client: TestClient) -> None:
    response = client.post(
        "/reports",
        files={"file": ("research.pdf", b"%PDF-1.7\n", "application/pdf")},
        data={"settings": '{"structure":"unknown"}'},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_upload"


def test_report_sections_are_editable_lockable_and_template_independent(
    client: TestClient,
) -> None:
    """Batch 9 updates derivatives while preserving one saved content model."""
    report_id = _create_report(client)

    state = client.get(f"/reports/{report_id}/editing")
    assert state.status_code == 200
    assert state.json()["revision"] == 1
    section_key = state.json()["sections"][0]["key"]

    edited = client.patch(
        f"/reports/{report_id}/sections/{section_key}",
        json={"content": "A clearer user-approved section grounded in the source."},
    )
    assert edited.status_code == 200
    assert edited.json()["revision"] == 2
    assert edited.json()["sections"][0]["edited"] is True
    assert "A clearer user-approved section" in client.get(
        f"/reports/{report_id}/html"
    ).text
    assert "A clearer user-approved section" in client.get(
        f"/reports/{report_id}/markdown"
    ).text

    locked = client.patch(
        f"/reports/{report_id}/sections/{section_key}/lock",
        json={"locked": True},
    )
    assert locked.status_code == 200
    assert locked.json()["sections"][0]["locked"] is True
    rejected = client.patch(
        f"/reports/{report_id}/sections/{section_key}",
        json={"content": "This must not replace approved content."},
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "report_section_locked"

    switched = client.patch(
        f"/reports/{report_id}/template",
        json={"template": "modern-research"},
    )
    assert switched.status_code == 200
    assert switched.json()["template_key"] == "modern-research"
    assert switched.json()["sections"][0]["content"].startswith(
        "A clearer user-approved section"
    )
    assert client.get(f"/reports/{report_id}").json()["template_key"] == (
        "modern-research"
    )

    blank = client.patch(
        f"/reports/{report_id}/sections/{section_key}/lock",
        json={"locked": False},
    )
    assert blank.status_code == 200
    rejected_blank = client.patch(
        f"/reports/{report_id}/sections/{section_key}",
        json={"content": "   "},
    )
    assert rejected_blank.status_code == 400
    assert rejected_blank.json()["error"]["code"] == "invalid_upload"


def test_report_section_transform_persists_provider_result(
    client: TestClient,
) -> None:
    class _Transformer:
        def transform(self, content: str, action: str, *, heading: str) -> object:
            del content, heading
            from app.reports.editor import SectionTransformResult

            return SectionTransformResult(
                content=f"Provider {action} result.",
                provider="gemini",
                fallback=False,
            )

    service = app.dependency_overrides[get_paperforge_service]()
    service._section_transformer = _Transformer()
    report_id = _create_report(client)
    section_key = client.get(f"/reports/{report_id}/editing").json()["sections"][0]["key"]

    response = client.post(
        f"/reports/{report_id}/sections/{section_key}/transform",
        json={"action": "shorten"},
    )

    assert response.status_code == 200
    assert response.json()["last_transform"] == {
        "action": "shorten",
        "provider": "gemini",
        "fallback": False,
    }
    assert response.json()["sections"][0]["content"] == "Provider shorten result."


def test_multi_upload_persists_ordered_sources_and_retrieves_without_rerunning(
    tmp_path: Path,
) -> None:
    service, pipeline = _service(tmp_path)
    app.dependency_overrides[get_paperforge_service] = lambda: service
    try:
        with TestClient(app) as client:
            report_id = _create_multi_report(client)
            for suffix in ("", "/html", "/markdown", "/pdf", "/metadata"):
                assert client.get(f"/reports/{report_id}{suffix}").status_code == 200
    finally:
        app.dependency_overrides.clear()

    report_directory = tmp_path / "reports" / str(report_id)
    assert sorted(path.name for path in (report_directory / "sources").iterdir()) == [
        "001_alpha.pdf", "002_beta.pdf"
    ]
    assert pipeline.many_calls == [
        ((report_directory / "sources" / "001_alpha.pdf", report_directory / "sources" / "002_beta.pdf"), ("alpha.pdf", "beta.pdf"))
    ]
    metadata = service.metadata(report_id)
    assert [item["filename"] for item in metadata["documents"]] == ["alpha.pdf", "beta.pdf"]


def test_regeneration_stages_copies_and_preserves_original_settings(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    app.dependency_overrides[get_paperforge_service] = lambda: service
    settings = {
        "project_title": "Regeneration source",
        "research_domain": "Software Engineering",
        "purpose": None,
        "structure": "professional",
        "visual_template": "paperforge-classic",
        "report_title": "Reliable Systems",
        "author": "Kalpesh Sharma",
        "organisation": None,
    }
    try:
        with TestClient(app) as client:
            response = client.post(
                "/reports",
                files={"file": ("evidence.pdf", b"%PDF original", "application/pdf")},
                data={"settings": json.dumps(settings)},
            )
            original_id = UUID(response.json()["report_id"])
    finally:
        app.dependency_overrides.clear()

    staged, restored_settings = service.stage_regeneration(original_id)
    assert isinstance(staged, StagedReport)
    assert staged.report_id != original_id
    assert staged.processing_path.read_bytes() == b"%PDF original"
    assert restored_settings is not None
    assert restored_settings.report_title == "Reliable Systems"
    assert (tmp_path / "reports" / str(original_id) / "input.pdf").read_bytes() == b"%PDF original"


def test_multi_report_regeneration_preserves_source_order(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    app.dependency_overrides[get_paperforge_service] = lambda: service
    try:
        with TestClient(app) as client:
            original_id = _create_multi_report(client)
    finally:
        app.dependency_overrides.clear()

    staged, restored_settings = service.stage_regeneration(original_id)

    assert isinstance(staged, StagedMultiReport)
    assert staged.report_id != original_id
    assert staged.source_filenames == ("alpha.pdf", "beta.pdf")
    assert [path.name for path in staged.source_paths] == [
        "001_alpha.pdf",
        "002_beta.pdf",
    ]
    assert [path.read_bytes() for path in staged.source_paths] == [
        b"%PDF-1.7\n",
        b"%PDF-1.7\n",
    ]
    assert restored_settings is None


def test_multi_upload_rejects_invalid_source_collections(client: TestClient) -> None:
    """The dedicated endpoint validates count, type, and provenance-safe names."""
    one = client.post("/reports/multi", files=[("files", ("one.pdf", b"%PDF", "application/pdf"))])
    duplicate = client.post("/reports/multi", files=[
        ("files", ("Alpha.pdf", b"%PDF", "application/pdf")),
        ("files", ("alpha.pdf", b"%PDF", "application/pdf")),
    ])
    non_pdf = client.post("/reports/multi", files=[
        ("files", ("one.pdf", b"%PDF", "application/pdf")),
        ("files", ("two.txt", b"text", "text/plain")),
    ])
    too_many = client.post("/reports/multi", files=[
        ("files", (f"{index}.pdf", b"%PDF", "application/pdf")) for index in range(6)
    ])

    assert [response.status_code for response in (one, duplicate, non_pdf, too_many)] == [400, 400, 400, 400]


def test_post_runs_synchronous_pdf_renderer_outside_the_asyncio_event_loop(
    tmp_path: Path,
) -> None:
    """POST generation runs the established blocking pipeline in a worker thread."""
    renderer = _LoopSensitivePDFRenderer()
    service, pipeline = _service(tmp_path, pdf_renderer=renderer)
    app.dependency_overrides[get_paperforge_service] = lambda: service
    try:
        with TestClient(app) as client:
            report_id = _create_report(client)
    finally:
        app.dependency_overrides.clear()

    report_directory = tmp_path / "reports" / str(report_id)
    assert renderer.executed_outside_event_loop is True
    assert pipeline.calls == [report_directory / "research.pdf"]
    assert (report_directory / "report.pdf").is_file()
    assert (report_directory / "report.json").is_file()
    assert (report_directory / "metadata.json").is_file()


def test_invalid_upload_missing_report_and_validation_errors_are_structured(
    client: TestClient,
) -> None:
    """HTTP failures use one safe JSON error envelope without traceback content."""
    invalid_upload = client.post(
        "/reports",
        files={"file": ("notes.txt", b"not a PDF", "text/plain")},
    )
    missing = client.get(f"/reports/{uuid4()}")
    malformed_id = client.get("/reports/not-a-uuid")

    assert invalid_upload.status_code == 400
    assert invalid_upload.json()["error"]["code"] == "invalid_upload"
    assert "traceback" not in invalid_upload.text.casefold()
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "report_not_found"
    assert malformed_id.status_code == 422
    assert malformed_id.json()["error"]["code"] == "request_validation_failed"


def test_rate_limit_fallback_completes_the_api_request(tmp_path: Path) -> None:
    """A fallback-bearing pipeline remains a successful report-generation flow."""
    service, _ = _service(tmp_path, fallback=True)
    app.dependency_overrides[get_paperforge_service] = lambda: service
    try:
        with TestClient(app) as client:
            report_id = _create_report(client)
            metadata = client.get(f"/reports/{report_id}/metadata")
    finally:
        app.dependency_overrides.clear()

    assert metadata.status_code == 200
    generation = metadata.json()["generation"]
    assert generation["provider"] == "fallback"
    assert generation["fallback"] is True
    assert generation["successful"] is True
    assert generation["reason"] == "rate_limit"


def test_provider_rate_limit_and_openapi_contracts_are_exposed_safely() -> None:
    """Provider boundary errors map to 429 and every endpoint appears in OpenAPI."""
    app.dependency_overrides[get_paperforge_service] = lambda: _RateLimitedService()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/reports",
                files={"file": ("research.pdf", b"%PDF-1.7\n", "application/pdf")},
            )
            openapi = client.get("/openapi.json")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "provider_rate_limited"
    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    assert "/health" in paths
    assert "/reports" in paths
    assert "/reports/jobs" in paths
    assert "/reports/jobs/multi" in paths
    assert "/reports/jobs/{job_id}" in paths
    assert "/reports/{report_id}" in paths
    assert "/reports/{report_id}/regenerate" in paths
    assert "/reports/{report_id}/html" in paths
    assert "/reports/{report_id}/pdf" in paths
    multi_operation = paths["/reports/multi"]["post"]
    multipart_schema = multi_operation["requestBody"]["content"][
        "multipart/form-data"
    ]["schema"]
    if "$ref" in multipart_schema:
        component_name = multipart_schema["$ref"].rsplit("/", 1)[-1]
        multipart_schema = openapi.json()["components"]["schemas"][component_name]
    files_schema = multipart_schema["properties"]["files"]
    assert files_schema["type"] == "array"
    assert files_schema["items"]["type"] == "string"
    assert files_schema["items"]["format"] == "binary"
    assert "/reports/{report_id}/markdown" in paths
    assert "/reports/{report_id}/metadata" in paths


def test_local_frontend_cors_and_release_version_are_exposed_safely() -> None:
    """Only configured Vite origins receive the unauthenticated local CORS policy."""
    with TestClient(app) as client:
        response = client.options(
            "/reports",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        health = client.get("/health")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "credentials" not in response.headers.get("access-control-allow-credentials", "")
    assert health.json()["version"] == "0.12.0"
