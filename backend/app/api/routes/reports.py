"""Synchronous report-generation and artifact-retrieval endpoints."""

from typing import Annotated
from uuid import UUID

from app.reports.presentation_models import PresentationModel

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from app.api.dependencies import get_paperforge_service
from app.schemas import ApiErrorResponse, MultiReportCreatedResponse, ReportCreatedResponse, ReportMetadataResponse
from app.services.report_service import GeneratedMultiReport, GeneratedReport, PaperForgeService

router = APIRouter(prefix="/reports", tags=["Reports"])

_ERROR_RESPONSES = {
    400: {"model": ApiErrorResponse, "description": "Invalid upload or PDF."},
    404: {"model": ApiErrorResponse, "description": "Report artifact not found."},
    422: {"model": ApiErrorResponse, "description": "Request validation failed."},
    429: {"model": ApiErrorResponse, "description": "Provider rate limit."},
    500: {"model": ApiErrorResponse, "description": "Artifact persistence failure."},
    503: {"model": ApiErrorResponse, "description": "Temporary provider failure."},
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
) -> ReportCreatedResponse:
    """Store one multipart PDF and invoke the service boundary exactly once."""
    try:
        result = await service.create_report(file)
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
) -> MultiReportCreatedResponse:
    """Store ordered PDFs and execute the single combined pipeline once."""
    try:
        result = await service.create_multi_report(files)
        return _multi_created_response(result)
    finally:
        for file in files:
            await file.close()


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
