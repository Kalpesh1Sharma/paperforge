"""Structured HTTP error translation for PaperForge domain boundaries."""

import logging
from typing import Callable

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.pipeline_service import (
    InvalidDocumentError,
    ProviderRateLimitedError,
    TemporaryProviderUnavailableError,
)
from app.services.report_service import (
    InvalidReportUploadError,
    ReportNotFoundError,
    ReportOutputError,
    ReportServiceError,
    ReportStorageError,
)
from app.integrations.superdocs import (
    SuperDocsNotConfiguredError,
    SuperDocsProtocolError,
    SuperDocsUnavailableError,
)
from app.services.review_service import (
    ReviewInvalidStateError,
    ReviewNotFoundError,
    ReviewVerificationError,
)
from app.projects import (
    ProjectConflictError,
    ProjectNotFoundError,
    ProjectStorageError,
    ProjectValidationError,
)
from app.jobs import ReportJobNotFoundError, ReportJobStorageError

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    """Return the middleware-generated request identifier or a safe fallback."""
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) and value else "unavailable"


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    """Build the one public failure shape without internal exception details."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": _request_id(request),
            }
        },
    )


async def invalid_upload_handler(
    request: Request,
    exc: InvalidReportUploadError,
) -> JSONResponse:
    """Return a client-safe response for invalid report multipart input."""
    return _error_response(
        request,
        status_code=status.HTTP_400_BAD_REQUEST,
        code="invalid_upload",
        message=str(exc),
    )


async def invalid_document_handler(
    request: Request,
    exc: InvalidDocumentError,
) -> JSONResponse:
    """Return a client-safe response for PDFs that cannot be processed."""
    return _error_response(
        request,
        status_code=status.HTTP_400_BAD_REQUEST,
        code="invalid_document",
        message=str(exc),
    )


async def report_not_found_handler(
    request: Request,
    exc: ReportNotFoundError,
) -> JSONResponse:
    """Return a stable 404 response for absent local report artifacts."""
    return _error_response(
        request,
        status_code=status.HTTP_404_NOT_FOUND,
        code="report_not_found",
        message=str(exc),
    )


async def rate_limit_handler(
    request: Request,
    exc: ProviderRateLimitedError,
) -> JSONResponse:
    """Expose rate limits without leaking provider response details."""
    return _error_response(
        request,
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        code="provider_rate_limited",
        message=str(exc),
    )


async def provider_unavailable_handler(
    request: Request,
    exc: TemporaryProviderUnavailableError,
) -> JSONResponse:
    """Map temporary nonrecoverable provider failures to service unavailable."""
    return _error_response(
        request,
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="provider_unavailable",
        message=str(exc),
    )


async def storage_error_handler(
    request: Request,
    exc: ReportStorageError | ReportOutputError,
) -> JSONResponse:
    """Avoid surfacing filesystem or renderer implementation detail to clients."""
    logger.error(
        "Report artifact failure | request_id=%s | path=%s | outcome=failure",
        _request_id(request),
        request.url.path,
    )
    return _error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="report_storage_failure",
        message="The report artifact could not be prepared.",
    )


async def project_not_found_handler(
    request: Request, exc: ProjectNotFoundError
) -> JSONResponse:
    return _error_response(
        request, status_code=404, code="project_not_found", message=str(exc)
    )


async def project_validation_handler(
    request: Request, exc: ProjectValidationError
) -> JSONResponse:
    return _error_response(
        request, status_code=400, code="invalid_project", message=str(exc)
    )


async def project_conflict_handler(
    request: Request, exc: ProjectConflictError
) -> JSONResponse:
    return _error_response(
        request, status_code=409, code="project_conflict", message=str(exc)
    )


async def project_storage_handler(
    request: Request, exc: ProjectStorageError
) -> JSONResponse:
    logger.error(
        "Project storage failure | request_id=%s | path=%s | outcome=failure",
        _request_id(request),
        request.url.path,
    )
    return _error_response(
        request,
        status_code=500,
        code="project_storage_failure",
        message="Project storage is temporarily unavailable.",
    )


async def report_job_not_found_handler(
    request: Request, exc: ReportJobNotFoundError
) -> JSONResponse:
    return _error_response(
        request, status_code=404, code="report_job_not_found", message=str(exc)
    )


async def report_job_storage_handler(
    request: Request, exc: ReportJobStorageError
) -> JSONResponse:
    logger.error(
        "Report job storage failure | request_id=%s | path=%s | outcome=failure",
        _request_id(request),
        request.url.path,
    )
    return _error_response(
        request,
        status_code=500,
        code="report_job_storage_failure",
        message="Report progress is temporarily unavailable.",
    )


async def review_not_found_handler(request: Request, exc: ReviewNotFoundError) -> JSONResponse:
    """Return a stable absence response for local review records and DOCX files."""
    return _error_response(request, status_code=404, code="review_not_found", message=str(exc))


async def review_state_handler(request: Request, exc: ReviewInvalidStateError) -> JSONResponse:
    """Require an explicit current pending change for every human decision."""
    return _error_response(request, status_code=409, code="review_invalid_state", message=str(exc))


async def review_unavailable_handler(
    request: Request,
    exc: SuperDocsNotConfiguredError | SuperDocsUnavailableError,
) -> JSONResponse:
    """Keep optional review configuration and provider outages safely opaque."""
    return _error_response(request, status_code=503, code="review_unavailable", message=str(exc))


async def review_protocol_handler(request: Request, exc: SuperDocsProtocolError) -> JSONResponse:
    """Avoid returning provider metadata when its documented contract is invalid."""
    return _error_response(request, status_code=503, code="review_protocol_error", message=str(exc))


async def review_verification_handler(request: Request, exc: ReviewVerificationError) -> JSONResponse:
    """Never claim successful completion when exported DOCX verification fails."""
    return _error_response(request, status_code=500, code="review_verification_failed", message=str(exc))


async def request_validation_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return structured validation failures instead of framework-default bodies."""
    return _error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="request_validation_failed",
        message="The request did not match the required API contract.",
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log internal errors server-side while preserving a safe public response."""
    logger.exception(
        "Unexpected API failure | request_id=%s | path=%s | outcome=failure",
        _request_id(request),
        request.url.path,
    )
    return _error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message="An unexpected server error occurred.",
    )


def install_error_handlers(app: FastAPI) -> None:
    """Install all route-agnostic exception mappings exactly once at app setup."""
    app.add_exception_handler(InvalidReportUploadError, invalid_upload_handler)
    app.add_exception_handler(InvalidDocumentError, invalid_document_handler)
    app.add_exception_handler(ReportNotFoundError, report_not_found_handler)
    app.add_exception_handler(ProviderRateLimitedError, rate_limit_handler)
    app.add_exception_handler(
        TemporaryProviderUnavailableError,
        provider_unavailable_handler,
    )
    app.add_exception_handler(ReportStorageError, storage_error_handler)
    app.add_exception_handler(ReportOutputError, storage_error_handler)
    app.add_exception_handler(ProjectNotFoundError, project_not_found_handler)
    app.add_exception_handler(ProjectValidationError, project_validation_handler)
    app.add_exception_handler(ProjectConflictError, project_conflict_handler)
    app.add_exception_handler(ProjectStorageError, project_storage_handler)
    app.add_exception_handler(ReportJobNotFoundError, report_job_not_found_handler)
    app.add_exception_handler(ReportJobStorageError, report_job_storage_handler)
    app.add_exception_handler(ReviewNotFoundError, review_not_found_handler)
    app.add_exception_handler(ReviewInvalidStateError, review_state_handler)
    app.add_exception_handler(SuperDocsNotConfiguredError, review_unavailable_handler)
    app.add_exception_handler(SuperDocsUnavailableError, review_unavailable_handler)
    app.add_exception_handler(SuperDocsProtocolError, review_protocol_handler)
    app.add_exception_handler(ReviewVerificationError, review_verification_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
