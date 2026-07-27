"""Business logic for validating and temporarily storing uploads."""

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import anyio
from fastapi import UploadFile

from app.models.upload import UploadBatchResponse, UploadedFileResponse

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = frozenset({".pdf", ".docx", ".md", ".txt"})
CHUNK_SIZE_BYTES = 1024 * 1024


class UploadValidationError(ValueError):
    """Raised when an upload does not meet the accepted file requirements."""


class UnsupportedFileTypeError(UploadValidationError):
    """Raised when a file extension is not supported."""


class UploadTooLargeError(UploadValidationError):
    """Raised when a file exceeds the configured upload size limit."""


class UploadStorageError(RuntimeError):
    """Raised when files cannot be safely persisted to temporary storage."""


class UploadService:
    """Validate upload requests and store their files beneath an upload ID."""

    def __init__(self, upload_dir: Path, max_upload_size_bytes: int) -> None:
        self._upload_dir = upload_dir
        self._max_upload_size_bytes = max_upload_size_bytes

    async def save_files(
        self,
        files: list[UploadFile],
        upload_id: UUID,
    ) -> UploadBatchResponse:
        """Save a validated collection of files and return upload metadata."""
        if not files:
            raise UploadValidationError("At least one file must be provided.")

        safe_filenames = [self._validate_file(upload_file) for upload_file in files]
        request_directory = self._upload_dir / str(upload_id)

        try:
            await anyio.to_thread.run_sync(
                lambda: request_directory.mkdir(parents=True, exist_ok=False)
            )

            uploaded_files: list[UploadedFileResponse] = []
            for index, (upload_file, safe_filename) in enumerate(
                zip(files, safe_filenames, strict=True),
                start=1,
            ):
                destination = request_directory / f"{index:03d}_{safe_filename}"
                file_size = await self._write_file(upload_file, destination)
                timestamp = datetime.now(timezone.utc)
                uploaded_files.append(
                    UploadedFileResponse(
                        filename=safe_filename,
                        content_type=upload_file.content_type,
                        file_size=file_size,
                        upload_timestamp=timestamp,
                    )
                )
        except UploadValidationError:
            await self._remove_request_directory(request_directory)
            raise
        except OSError as exc:
            await self._remove_request_directory(request_directory)
            logger.exception("Unable to store upload %s", upload_id)
            raise UploadStorageError("Unable to store uploaded files.") from exc
        except Exception as exc:
            await self._remove_request_directory(request_directory)
            logger.exception("Unexpected error while storing upload %s", upload_id)
            raise UploadStorageError("Unable to store uploaded files.") from exc

        completed_at = datetime.now(timezone.utc)
        logger.info(
            "Stored upload %s containing %d file(s) in %s",
            upload_id,
            len(uploaded_files),
            request_directory,
        )
        return UploadBatchResponse(
            upload_id=upload_id,
            upload_timestamp=completed_at,
            files=uploaded_files,
        )

    def _validate_file(self, upload_file: UploadFile) -> str:
        """Return a safe filename after enforcing the allowed extension list."""
        if not upload_file.filename:
            raise UploadValidationError("Every uploaded file must have a filename.")

        safe_filename = Path(upload_file.filename.replace("\\", "/")).name
        if safe_filename in {"", ".", ".."} or "\x00" in safe_filename:
            raise UploadValidationError("An uploaded filename is invalid.")

        extension = Path(safe_filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            allowed_extensions = ", ".join(sorted(ALLOWED_EXTENSIONS))
            raise UnsupportedFileTypeError(
                f"Unsupported file type for '{safe_filename}'. "
                f"Allowed extensions: {allowed_extensions}."
            )

        return safe_filename

    async def _write_file(self, upload_file: UploadFile, destination: Path) -> int:
        """Stream an UploadFile to disk and enforce the per-file size limit."""
        file_size = 0
        async with await anyio.open_file(destination, "wb") as destination_file:
            while chunk := await upload_file.read(CHUNK_SIZE_BYTES):
                file_size += len(chunk)
                if file_size > self._max_upload_size_bytes:
                    raise UploadTooLargeError(
                        f"'{upload_file.filename}' exceeds the maximum allowed "
                        "file size."
                    )
                await destination_file.write(chunk)

        return file_size

    async def _remove_request_directory(self, request_directory: Path) -> None:
        """Best-effort cleanup for a failed upload request."""
        if not request_directory.exists():
            return

        try:
            await anyio.to_thread.run_sync(shutil.rmtree, request_directory)
        except OSError:
            logger.exception(
                "Unable to clean up failed upload directory %s", request_directory
            )
