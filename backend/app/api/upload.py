"""Versioned HTTP endpoints for temporary document uploads."""

import logging
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import settings
from app.models.upload import UploadBatchResponse
from app.services.upload_service import (
    UnsupportedFileTypeError,
    UploadService,
    UploadStorageError,
    UploadTooLargeError,
    UploadValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/upload", tags=["Upload"])
upload_service = UploadService(
    upload_dir=settings.upload_dir,
    max_upload_size_bytes=settings.max_upload_size_bytes,
)


@router.post(
    "",
    response_model=UploadBatchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload one or more research documents",
)
async def upload_files(
    files: Annotated[
        list[UploadFile],
        File(description="One or more PDF, DOCX, Markdown, or text files."),
    ],
) -> UploadBatchResponse:
    """Validate and temporarily store a batch of uploaded research files."""
    upload_id = uuid4()

    try:
        return await upload_service.save_files(files, upload_id)
    except UnsupportedFileTypeError as exc:
        logger.warning("Rejected unsupported file type for upload %s: %s", upload_id, exc)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    except UploadTooLargeError as exc:
        logger.warning("Rejected oversized file for upload %s: %s", upload_id, exc)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except UploadValidationError as exc:
        logger.warning("Rejected invalid upload %s: %s", upload_id, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except UploadStorageError as exc:
        logger.error("Failed to persist upload %s", upload_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to store uploaded files.",
        ) from exc
    finally:
        for upload_file in files:
            await upload_file.close()
