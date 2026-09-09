"""Synchronous report-generation and artifact-retrieval endpoints."""

from typing import Annotated
from uuid import UUID

from app.reports.presentation_models import PresentationModel

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from app.api.dependencies import (
    get_paperforge_service,
    get_report_job_reader,
    get_report_job_service,
    get_review_service,
)
from app.jobs import ReportJobReader, ReportJobRecord, ReportJobService
from app.schemas import (
    ApiErrorResponse,
    MultiReportCreatedResponse,
    ReportCreatedResponse,
    ReportJobResponse,
    ReportMetadataResponse,
    ReviewDecisionRequest,
    ReviewStateResponse,
)
from app.services.report_service import (
    GeneratedMultiReport,
    GeneratedReport,
    InvalidReportUploadError,
    PaperForgeService,
)
from app.services.review_service import ReviewService
from app.reports import ReportGenerationSettings
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/reports", tags=["Reports"])


def _generation_settings(value: str | None) -> ReportGenerationSettings | None:
    """Validate the optional JSON wizard payload carried by multipart forms."""
    if value is None:
        return None
    try:
        return ReportGenerationSettings.model_validate_json(value)
    except (ValidationError, ValueError) as exc:
        raise InvalidReportUploadError(
            "The report configuration is incomplete or invalid."
        ) from exc

_ERROR_RESPONSES = {
    400: {"model": ApiErrorResponse, "description": "Invalid upload or PDF."},
    404: {"model": ApiErrorResponse, "description": "Report artifact not found."},
    422: {"model": ApiErrorResponse, "description": "Request validation failed."},
    429: {"model": ApiErrorResponse, "description": "Provider rate limit."},
    500: {"model": ApiErrorResponse, "description": "Artifact persistence failure."},
    503: {"model": ApiErrorResponse, "description": "Temporary provider failure."},
}

_REVIEW_ERROR_RESPONSES = {
    **_ERROR_RESPONSES,
    409: {"model": ApiErrorResponse, "description": "Review is not awaiting this decision."},
}


def _created_response(result: GeneratedReport) -> ReportCreatedResponse:
    """Translate a service result into the stable upload response contract."""
    document = result.source_document
    return ReportCreatedResponse.model_validate(
        {
            "report_id": result.report_id,
            "available_formats": result.available_formats,
            "metadata": {
                "filename": document.filename,
                "file_type": document.file_type,
                "page_count": document.page_count,
                "word_count": document.word_count,
                "character_count": document.character_count,
            },
        }
    )


def _multi_created_response(result: GeneratedMultiReport) -> MultiReportCreatedResponse:
    return MultiReportCreatedResponse.model_validate(
        {
            "report_id": result.report_id,
            "available_formats": result.available_formats,
            "documents": [
                {
                    "filename": document.filename,
                    "file_type": document.file_type,
                    "page_count": document.page_count,
                    "word_count": document.word_count,
                    "character_count": document.character_count,
                }
                for document in result.source_documents
            ],
        }
    )


def _review_response(state: object) -> ReviewStateResponse:
    """Translate the internal immutable review record to its public contract."""
    payload = state.model_dump()  # type: ignore[union-attr]
    return ReviewStateResponse.model_validate(
        {
            key: payload[key]
            for key in (
                "report_id",
                "status",
                "pending_changes",
                "approved_changes",
                "rejected_changes",
                "final_docx_available",
            )
        }
    )


def _job_response(job: ReportJobRecord) -> ReportJobResponse:
    """Expose progress without source paths, settings JSON, or exception detail."""
    return ReportJobResponse.model_validate(
        {
            "job_id": job.job_id,
            "report_id": job.report_id,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "message": job.message,
            "source_filenames": job.source_filenames,
            "provider": job.provider,
            "fallback": job.fallback,
            "error": (
                {"code": job.error_code, "message": job.error_message}
                if job.error_code and job.error_message
                else None
            ),
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "completed_at": job.completed_at,
        }
    )


@router.post(
    "/jobs",
    response_model=ReportJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_ERROR_RESPONSES,
    summary="Upload one PDF and start background report generation",
)
async def create_report_job(
    background_tasks: BackgroundTasks,
    file: Annotated[
        UploadFile,
        File(description="Research PDF to process.", media_type="application/pdf"),
    ],
    service: Annotated[ReportJobService, Depends(get_report_job_service)],
    settings: Annotated[
        str | None, Form(description="JSON report wizard settings.")
    ] = None,
) -> ReportJobResponse:
    """Persist the upload, return promptly, and generate outside the request."""
    try:
        job = await service.submit_report(file, _generation_settings(settings))
        background_tasks.add_task(service.run, job.job_id)
        return _job_response(job)
    finally:
        await file.close()


@router.post(
    "/jobs/multi",
    response_model=ReportJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_ERROR_RESPONSES,
    summary="Upload ordered PDFs and start background report generation",
)
async def create_multi_report_job(
    background_tasks: BackgroundTasks,
    files: Annotated[
        list[UploadFile],
        File(
            description="Ordered research PDFs to process.",
            media_type="application/pdf",
            json_schema_extra={"items": {"type": "string", "format": "binary"}},
        ),
    ],
    service: Annotated[ReportJobService, Depends(get_report_job_service)],
    settings: Annotated[
        str | None, Form(description="JSON report wizard settings.")
    ] = None,
) -> ReportJobResponse:
    """Persist every source before request-owned upload handles are closed."""
    try:
        job = await service.submit_multi_report(files, _generation_settings(settings))
        background_tasks.add_task(service.run, job.job_id)
        return _job_response(job)
    finally:
        for file in files:
            await file.close()


@router.get(
    "/jobs/{job_id}",
    response_model=ReportJobResponse,
    responses=_ERROR_RESPONSES,
    summary="Retrieve persistent report-generation progress",
)
def get_report_job(
    job_id: UUID,
    service: Annotated[ReportJobReader, Depends(get_report_job_reader)],
) -> ReportJobResponse:
    """Read stored progress without performing or restarting generation."""
    return _job_response(service.get(job_id))


@router.post(
    "/{report_id}/regenerate",
    response_model=ReportJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_ERROR_RESPONSES,
    summary="Regenerate a completed report from its stored sources",
)
def regenerate_report(
    report_id: UUID,
    background_tasks: BackgroundTasks,
    service: Annotated[ReportJobService, Depends(get_report_job_service)],
) -> ReportJobResponse:
    """Create a new background job while preserving the original report."""
    job = service.submit_regeneration(report_id)
    background_tasks.add_task(service.run, job.job_id)
    return _job_response(job)


@router.post(
    "",
    response_model=ReportCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERROR_RESPONSES,
    summary="Upload one PDF and generate a complete report",
    description=(
        "Synchronously runs the existing PaperForge pipeline and stores JSON, "
        "Markdown, HTML, and PDF artifacts for later retrieval."
    ),
)
async def create_report(
    file: Annotated[
        UploadFile,
        File(
            description="Research PDF to process.",
            media_type="application/pdf",
        ),
    ],
    service: Annotated[PaperForgeService, Depends(get_paperforge_service)],
    settings: Annotated[str | None, Form(description="JSON report wizard settings.")] = None,
) -> ReportCreatedResponse:
    """Store one multipart PDF and invoke the service boundary exactly once."""
    try:
        configuration = _generation_settings(settings)
        result = (
            await service.create_report(file)
            if configuration is None
            else await service.create_report(file, configuration)
        )
        return _created_response(result)
    finally:
        await file.close()


@router.post(
    "/multi",
    response_model=MultiReportCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERROR_RESPONSES,
    summary="Upload 2–5 PDFs and generate one grounded report",
)
async def create_multi_report(
    files: Annotated[
        list[UploadFile],
        File(
            description="Ordered research PDFs to process.",
            media_type="application/pdf",
            json_schema_extra={"items": {"type": "string", "format": "binary"}},
        ),
    ],
    service: Annotated[PaperForgeService, Depends(get_paperforge_service)],
    settings: Annotated[str | None, Form(description="JSON report wizard settings.")] = None,
) -> MultiReportCreatedResponse:
    """Store ordered PDFs and execute the single combined pipeline once."""
    try:
        configuration = _generation_settings(settings)
        result = (
            await service.create_multi_report(files)
            if configuration is None
            else await service.create_multi_report(files, configuration)
        )
        return _multi_created_response(result)
    finally:
        for file in files:
            await file.close()


@router.post(
    "/{report_id}/review",
    response_model=ReviewStateResponse,
    responses=_REVIEW_ERROR_RESPONSES,
    summary="Start one explicit-approval Executive Summary review",
)
async def start_review(
    report_id: UUID,
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewStateResponse:
    """Start or return an idempotent SuperDocs review from stored report HTML."""
    return _review_response(await run_in_threadpool(service.start_review, report_id))


@router.get(
    "/{report_id}/review",
    response_model=ReviewStateResponse,
    responses=_REVIEW_ERROR_RESPONSES,
    summary="Retrieve persisted local review state",
)
def get_review(
    report_id: UUID,
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewStateResponse:
    """Read local review state only; this route never polls SuperDocs."""
    return _review_response(service.get_review(report_id))


@router.post(
    "/{report_id}/review/approve",
    response_model=ReviewStateResponse,
    responses=_REVIEW_ERROR_RESPONSES,
    summary="Approve one proposed document change",
)
async def approve_review_change(
    report_id: UUID,
    request: ReviewDecisionRequest,
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewStateResponse:
    """Never approve another change implicitly or infer approval from state."""
    return _review_response(
        await run_in_threadpool(service.approve, report_id, request.change_id)
    )


@router.post(
    "/{report_id}/review/reject",
    response_model=ReviewStateResponse,
    responses=_REVIEW_ERROR_RESPONSES,
    summary="Reject one proposed document change",
)
async def reject_review_change(
    report_id: UUID,
    request: ReviewDecisionRequest,
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> ReviewStateResponse:
    """Reject exactly one pending proposal, optionally with human feedback."""
    return _review_response(
        await run_in_threadpool(
            service.reject, report_id, request.change_id, request.feedback
        )
    )


@router.get(
    "/{report_id}/docx",
    response_class=FileResponse,
    responses=_REVIEW_ERROR_RESPONSES,
    summary="Retrieve the verified human-reviewed DOCX",
)
def get_reviewed_docx(
    report_id: UUID,
    service: Annotated[ReviewService, Depends(get_review_service)],
) -> FileResponse:
    """Stream only a prior verified export; GET never generates a document."""
    return FileResponse(
        path=service.docx_path(report_id),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"paperforge-{report_id}-reviewed.docx",
    )


@router.get(
    "/{report_id}/html",
    response_class=HTMLResponse,
    responses=_ERROR_RESPONSES,
    summary="Retrieve a standalone HTML report",
)
def get_html_report(
    report_id: UUID,
    service: Annotated[PaperForgeService, Depends(get_paperforge_service)],
) -> HTMLResponse:
    """Return the previously generated HTML without recomposing presentation data."""
    return HTMLResponse(content=service.html(report_id))


@router.get(
    "/{report_id}/pdf",
    response_class=FileResponse,
    responses=_ERROR_RESPONSES,
    summary="Retrieve a publication-ready PDF report",
)
def get_pdf_report(
    report_id: UUID,
    service: Annotated[PaperForgeService, Depends(get_paperforge_service)],
) -> FileResponse:
    """Stream the durable PDF artifact created by the existing PDF renderer."""
    return FileResponse(
        path=service.pdf_path(report_id),
        media_type="application/pdf",
        filename=f"paperforge-{report_id}.pdf",
    )


@router.get(
    "/{report_id}/markdown",
    response_class=PlainTextResponse,
    responses=_ERROR_RESPONSES,
    summary="Retrieve a Markdown report",
)
def get_markdown_report(
    report_id: UUID,
    service: Annotated[PaperForgeService, Depends(get_paperforge_service)],
) -> PlainTextResponse:
    """Return the stored Markdown publication with a text/markdown media type."""
    return PlainTextResponse(
        content=service.markdown(report_id),
        media_type="text/markdown",
    )


@router.get(
    "/{report_id}/metadata",
    response_model=ReportMetadataResponse,
    responses=_ERROR_RESPONSES,
    summary="Retrieve report generation metadata",
)
def get_report_metadata(
    report_id: UUID,
    service: Annotated[PaperForgeService, Depends(get_paperforge_service)],
) -> ReportMetadataResponse:
    """Return only document and provider metadata, never the report body."""
    return ReportMetadataResponse.model_validate(service.metadata(report_id))


@router.get(
    "/{report_id}",
    response_model=PresentationModel,
    responses=_ERROR_RESPONSES,
    summary="Retrieve the composed PresentationModel as JSON",
)
def get_report_json(
    report_id: UUID,
    service: Annotated[PaperForgeService, Depends(get_paperforge_service)],
) -> JSONResponse:
    """Return the exact persisted immutable presentation model as JSON."""
    presentation = service.presentation(report_id)
    return JSONResponse(content=presentation.model_dump(mode="json", warnings="error"))
