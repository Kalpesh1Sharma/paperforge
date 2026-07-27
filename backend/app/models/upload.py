"""Schemas for file upload responses."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class UploadedFileResponse(BaseModel):
    """Metadata for one file that has been stored successfully."""

    filename: str = Field(..., description="Original name supplied by the client.")
    content_type: str | None = Field(
        default=None,
        description="Content type supplied in the multipart request.",
    )
    file_size: int = Field(..., ge=0, description="Stored file size in bytes.")
    upload_timestamp: datetime = Field(
        ...,
        description="UTC timestamp at which the upload completed.",
    )
    status: Literal["uploaded"] = "uploaded"


class UploadBatchResponse(BaseModel):
    """Response returned after all files in a request have been stored."""

    upload_id: UUID = Field(..., description="UUID4 assigned to this upload request.")
    upload_timestamp: datetime = Field(
        ...,
        description="UTC timestamp at which the upload request completed.",
    )
    status: Literal["uploaded"] = "uploaded"
    files: list[UploadedFileResponse] = Field(
        ...,
        min_length=1,
        description="Metadata for every stored file.",
    )
