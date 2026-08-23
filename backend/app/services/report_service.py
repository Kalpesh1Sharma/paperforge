"""Local report storage and high-level synchronous service orchestration."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.models.parsed_document import ParsedDocument
from app.reports import HTMLRenderer, MarkdownRenderer, PDFRenderer, PresentationModel
from app.reports.exceptions import ReportRenderingError
from app.services.pipeline_service import (
    MultiDocumentPipelineArtifacts,
    PipelineArtifacts,
    PipelineService,
)
from app.services.upload_service import (
    UnsupportedFileTypeError,
    UploadService,
    UploadStorageError,
    UploadTooLargeError,
    UploadValidationError,
)

logger = logging.getLogger(__name__)

ReportFormat = Literal["all", "json", "html", "markdown", "pdf"]
StoredFormat = Literal["json", "html", "markdown", "pdf"]
_AVAILABLE_FORMATS: tuple[StoredFormat, ...] = ("json", "html", "markdown", "pdf")


class ReportServiceError(RuntimeError):
    """Base exception raised by the local report-service boundary."""


class InvalidReportUploadError(ReportServiceError):
    """Raised when a report request does not contain one usable PDF."""


class ReportNotFoundError(ReportServiceError):
    """Raised when a report ID has no completed local artifacts."""


class ReportStorageError(ReportServiceError):
    """Raised when local report artifacts cannot be persisted or read safely."""


class ReportOutputError(ReportServiceError):
    """Raised when a renderer cannot materialize a requested artifact."""


@dataclass(frozen=True, slots=True)
class GeneratedReport:
    """Storage-safe summary of one completed report-generation request."""

    report_id: UUID
    available_formats: tuple[StoredFormat, ...]
    source_document: ParsedDocument
    generation_metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class GeneratedMultiReport:
    """Storage-safe summary of one completed multi-source request."""

    report_id: UUID
    available_formats: tuple[StoredFormat, ...]
    source_documents: tuple[ParsedDocument, ...]
    generation_metadata: dict[str, object]


class LocalReportStore:
    """Filesystem-backed report store with replaceable service-facing methods."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = Path(root_dir)

    @property
    def root_dir(self) -> Path:
        """Return the configured local artifact root without creating it."""
        return self._root_dir

    def report_directory(self, report_id: UUID) -> Path:
        """Return the deterministic child directory for a UUID report ID."""
        if not isinstance(report_id, UUID):
            raise ReportStorageError("Report identifiers must be UUID values.")
        return self._root_dir / str(report_id)

    def input_path(self, report_id: UUID) -> Path:
        """Return the canonical input path for a stored report."""
        return self.report_directory(report_id) / "input.pdf"

    def artifact_path(self, report_id: UUID, artifact_name: str) -> Path:
        """Return one fixed artifact path without accepting path traversal."""
        allowed_names = {
            "report.json",
            "report.html",
            "report.md",
            "report.pdf",
            "metadata.json",
        }
        if artifact_name not in allowed_names:
            raise ReportStorageError("Requested report artifact is not supported.")
        return self.report_directory(report_id) / artifact_name

    def ensure_report_directory(self, report_id: UUID) -> Path:
        """Create and return a report directory for one newly allocated UUID."""
        directory = self.report_directory(report_id)
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise ReportStorageError("A report with this identifier already exists.") from exc
        except OSError as exc:
            raise ReportStorageError("Unable to create report storage.") from exc
        return directory

    def has_completed_report(self, report_id: UUID) -> bool:
        """Return whether the required persisted report model is available."""
        return self.artifact_path(report_id, "report.json").is_file()

    def write_text(self, report_id: UUID, artifact_name: str, value: str) -> Path:
        """Atomically persist one UTF-8 textual artifact below its report folder."""
        if not isinstance(value, str):
            raise ReportStorageError("Text report artifacts must be strings.")
        destination = self.artifact_path(report_id, artifact_name)
        self._write_bytes(destination, value.encode("utf-8"))
        return destination

    def write_json(self, report_id: UUID, artifact_name: str, value: object) -> Path:
        """Atomically serialize one JSON artifact with stable key ordering."""
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ReportStorageError("Report metadata is not JSON serializable.") from exc
        destination = self.artifact_path(report_id, artifact_name)
        self._write_bytes(destination, encoded)
        return destination

    def read_text(self, report_id: UUID, artifact_name: str) -> str:
        """Read one completed textual artifact or raise a not-found error."""
        path = self._completed_artifact_path(report_id, artifact_name)
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ReportStorageError("Unable to read the stored report artifact.") from exc

    def read_json(self, report_id: UUID, artifact_name: str) -> object:
        """Read one completed JSON artifact without returning arbitrary files."""
        try:
            return json.loads(self.read_text(report_id, artifact_name))
        except json.JSONDecodeError as exc:
            raise ReportStorageError("Stored report JSON is invalid.") from exc

    def file_path(self, report_id: UUID, artifact_name: str) -> Path:
        """Return an existing binary artifact suitable for a file response."""
        return self._completed_artifact_path(report_id, artifact_name)

    def finalize_uploaded_input(self, report_id: UUID, temporary_path: Path) -> Path:
        """Rename the validated upload to its canonical local report path."""
        source = Path(temporary_path)
        destination = self.input_path(report_id)
        try:
            source.replace(destination)
        except OSError as exc:
            raise ReportStorageError("Unable to finalize the uploaded PDF.") from exc
        return destination

    def finalize_uploaded_sources(
        self,
        report_id: UUID,
        temporary_paths: tuple[Path, ...],
        filenames: tuple[str, ...],
    ) -> tuple[Path, ...]:
        """Move staged uploads into ordered multi-source storage safely."""
        if len(temporary_paths) != len(filenames):
            raise ReportStorageError("Uploaded source metadata is inconsistent.")
        sources = self.report_directory(report_id) / "sources"
        try:
            sources.mkdir(exist_ok=False)
            destinations = tuple(
                sources / f"{index:03d}_{filename}"
                for index, filename in enumerate(filenames, start=1)
            )
            for source, destination in zip(temporary_paths, destinations, strict=True):
                Path(source).replace(destination)
        except OSError as exc:
            raise ReportStorageError("Unable to finalize uploaded source PDFs.") from exc
        return destinations

    def _completed_artifact_path(self, report_id: UUID, artifact_name: str) -> Path:
        path = self.artifact_path(report_id, artifact_name)
        if not self.has_completed_report(report_id):
            raise ReportNotFoundError("Report was not found.")
        if not path.is_file():
            raise ReportNotFoundError("Requested report format is not available.")
        return path

    @staticmethod
    def _write_bytes(destination: Path, value: bytes) -> None:
        """Replace one artifact only after its complete temporary write succeeds."""
        try:
            if not destination.parent.is_dir():
                raise ReportStorageError("Report storage directory is missing.")
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
            )
            temporary_path = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as temporary_file:
                    temporary_file.write(value)
                temporary_path.replace(destination)
            finally:
                if temporary_path.exists():
                    temporary_path.unlink(missing_ok=True)
        except ReportStorageError:
            raise
        except OSError as exc:
            raise ReportStorageError("Unable to persist report artifact.") from exc


class PaperForgeService:
    """Generate and persist reports by composing the established pipeline.

    Route handlers delegate here after FastAPI has parsed the multipart upload.
    The service contains no domain transformation: it stages the input, calls
    the existing pipeline once, and persists renderer outputs.
    """

    def __init__(
        self,
        *,
        store: LocalReportStore,
        pipeline_service: PipelineService,
        upload_service: UploadService,
        markdown_renderer: MarkdownRenderer | None = None,
        html_renderer: HTMLRenderer | None = None,
        pdf_renderer: PDFRenderer | None = None,
    ) -> None:
        self._store = store
        self._pipeline_service = pipeline_service
        self._upload_service = upload_service
        self._markdown_renderer = markdown_renderer or MarkdownRenderer()
        self._html_renderer = html_renderer or HTMLRenderer()
        self._pdf_renderer = pdf_renderer or PDFRenderer()

    async def create_report(self, uploaded_file: UploadFile) -> GeneratedReport:
        """Stream one PDF upload into local storage, then generate all formats."""
        self._validate_pdf_upload(uploaded_file)
        report_id = uuid4()
        try:
            upload_response = await self._upload_service.save_files(
                [uploaded_file],
                report_id,
            )
        except UnsupportedFileTypeError as exc:
            raise InvalidReportUploadError("Only PDF uploads are accepted.") from exc
        except (UploadTooLargeError, UploadValidationError) as exc:
            raise InvalidReportUploadError(str(exc)) from exc
        except UploadStorageError as exc:
            raise ReportStorageError("Unable to persist the uploaded PDF.") from exc

        stored_file = upload_response.files[0]
        temporary_path = self._store.report_directory(report_id) / (
            f"001_{stored_file.filename}"
        )
        input_path = self._store.finalize_uploaded_input(report_id, temporary_path)
        return await run_in_threadpool(
            self.generate_report,
            input_path,
            "all",
            report_id=report_id,
        )

    async def create_multi_report(
        self,
        uploaded_files: list[UploadFile],
    ) -> GeneratedMultiReport:
        """Stage 2–5 PDFs, then run one ordered combined pipeline in a worker."""
        if not 2 <= len(uploaded_files) <= 5:
            raise InvalidReportUploadError("Provide between 2 and 5 PDF files.")
        filenames = tuple(self._validate_pdf_upload(file) for file in uploaded_files)
        if len({name.casefold() for name in filenames}) != len(filenames):
            raise InvalidReportUploadError("Uploaded PDF filenames must be unique.")
        report_id = uuid4()
        try:
            upload_response = await self._upload_service.save_files(uploaded_files, report_id)
        except UnsupportedFileTypeError as exc:
            raise InvalidReportUploadError("Only PDF uploads are accepted.") from exc
        except (UploadTooLargeError, UploadValidationError) as exc:
            raise InvalidReportUploadError(str(exc)) from exc
        except UploadStorageError as exc:
            raise ReportStorageError("Unable to persist uploaded PDFs.") from exc
        temporary_paths = tuple(
            self._store.report_directory(report_id) / f"{index:03d}_{file.filename}"
            for index, file in enumerate(upload_response.files, start=1)
        )
        source_paths = self._store.finalize_uploaded_sources(
            report_id, temporary_paths, filenames
        )
        return await run_in_threadpool(
            self.generate_multi_report,
            source_paths,
            filenames,
            "all",
            report_id=report_id,
        )

    def generate_report(
        self,
        uploaded_file: Path,
        output_format: ReportFormat = "all",
        *,
        report_id: UUID | None = None,
    ) -> GeneratedReport:
        """Run the full synchronous pipeline for one already-persisted PDF.

        ``output_format`` permits focused service callers while the HTTP upload
        endpoint intentionally requests ``all`` so every retrieval endpoint is
        ready immediately after a successful POST.
        """
        if output_format not in {"all", "json", "html", "markdown", "pdf"}:
            raise InvalidReportUploadError("Requested output format is not supported.")

        path = Path(uploaded_file)
        if path.suffix.lower() != ".pdf":
            raise InvalidReportUploadError("Only PDF uploads are accepted.")

        active_report_id = report_id or uuid4()
        if report_id is None:
            directory = self._store.ensure_report_directory(active_report_id)
            try:
                shutil.copyfile(path, directory / "input.pdf")
            except OSError as exc:
                raise ReportStorageError("Unable to store the uploaded PDF.") from exc
            path = directory / "input.pdf"

        artifacts = self._pipeline_service.process(path)
        formats = self._materialize_artifacts(
            active_report_id,
            artifacts,
            output_format,
        )
        return GeneratedReport(
            report_id=active_report_id,
            available_formats=formats,
            source_document=artifacts.source_document,
            generation_metadata=self._generation_metadata(artifacts),
        )

    def generate_multi_report(
        self,
        source_paths: tuple[Path, ...],
        source_filenames: tuple[str, ...],
        output_format: ReportFormat = "all",
        *,
        report_id: UUID,
    ) -> GeneratedMultiReport:
        """Run one combined pipeline over already-persisted ordered PDFs."""
        if output_format not in {"all", "json", "html", "markdown", "pdf"}:
            raise InvalidReportUploadError("Requested output format is not supported.")
        artifacts = self._pipeline_service.process_many(source_paths, source_filenames)
        formats = self._materialize_artifacts(report_id, artifacts, output_format)
        return GeneratedMultiReport(
            report_id=report_id,
            available_formats=formats,
            source_documents=artifacts.source_documents,
            generation_metadata=self._generation_metadata(artifacts),
        )

    def presentation(self, report_id: UUID) -> PresentationModel:
        """Load the immutable presentation JSON that backs report retrieval."""
        try:
            return PresentationModel.model_validate_json(
                self._store.read_text(report_id, "report.json")
            )
        except (ValidationError, ValueError) as exc:
            raise ReportStorageError("Stored presentation model is invalid.") from exc

    def metadata(self, report_id: UUID) -> dict[str, object]:
        """Load the deliberately body-free metadata artifact for one report."""
        payload = self._store.read_json(report_id, "metadata.json")
        if not isinstance(payload, dict):
            raise ReportStorageError("Stored report metadata is invalid.")
        return payload

    def html(self, report_id: UUID) -> str:
        """Return the durable standalone HTML representation."""
        return self._store.read_text(report_id, "report.html")

    def markdown(self, report_id: UUID) -> str:
        """Return the durable Markdown representation."""
        return self._store.read_text(report_id, "report.md")

    def pdf_path(self, report_id: UUID) -> Path:
        """Return the durable PDF artifact path for FastAPI file streaming."""
        return self._store.file_path(report_id, "report.pdf")

    def _materialize_artifacts(
        self,
        report_id: UUID,
        artifacts: PipelineArtifacts | MultiDocumentPipelineArtifacts,
        output_format: ReportFormat,
    ) -> tuple[StoredFormat, ...]:
        """Persist requested immutable outputs with no renderer recomposition."""
        formats = self._requested_formats(output_format)
        try:
            if "markdown" in formats:
                self._store.write_text(
                    report_id,
                    "report.md",
                    self._markdown_renderer.render_presentation(artifacts.presentation),
                )
            if "html" in formats:
                self._store.write_text(
                    report_id,
                    "report.html",
                    self._html_renderer.render_presentation(artifacts.presentation),
                )
            if "pdf" in formats:
                self._pdf_renderer.render_presentation(
                    artifacts.presentation,
                    self._store.artifact_path(report_id, "report.pdf"),
                )
            # The presentation JSON marks a directory as complete. Write it
            # only after all selected renderers succeed.
            self._store.write_json(
                report_id,
                "report.json",
                artifacts.presentation.model_dump(mode="json", warnings="error"),
            )
            self._store.write_json(
                report_id,
                "metadata.json",
                self._metadata_payload(report_id, artifacts, formats),
            )
        except ReportRenderingError as exc:
            raise ReportOutputError("Unable to render the requested report output.") from exc
        except ReportStorageError:
            raise
        except OSError as exc:
            raise ReportStorageError("Unable to persist report artifacts.") from exc
        return formats

    @staticmethod
    def _requested_formats(output_format: ReportFormat) -> tuple[StoredFormat, ...]:
        """Return stable report-format order for a service request."""
        if output_format == "all":
            return _AVAILABLE_FORMATS
        if output_format == "json":
            return ("json",)
        return ("json", output_format)

    @staticmethod
    def _validate_pdf_upload(uploaded_file: UploadFile) -> str:
        """Reject absent or non-PDF multipart filenames before file I/O begins."""
        filename = uploaded_file.filename
        if not isinstance(filename, str) or not filename.strip():
            raise InvalidReportUploadError("A PDF file is required.")
        safe_filename = Path(filename.replace("\\", "/")).name
        if safe_filename in {"", ".", ".."} or "\x00" in safe_filename:
            raise InvalidReportUploadError("A PDF file is required.")
        if Path(safe_filename).suffix.lower() != ".pdf":
            raise InvalidReportUploadError("Only PDF uploads are accepted.")
        return safe_filename

    @staticmethod
    def _generation_metadata(
        artifacts: PipelineArtifacts | MultiDocumentPipelineArtifacts,
    ) -> dict[str, object]:
        """Select safe synthesis telemetry without report text or source payloads."""
        metadata = artifacts.enhanced_report.synthesis_metadata
        return {
            "status": "completed",
            "provider": metadata.provider,
            "model": metadata.model,
            "elapsed_ms": metadata.elapsed_ms,
            "successful": metadata.successful,
            "fallback": metadata.fallback,
            "enhanced": metadata.enhanced,
            "reason": metadata.reason,
        }

    @classmethod
    def _metadata_payload(
        cls,
        report_id: UUID,
        artifacts: PipelineArtifacts | MultiDocumentPipelineArtifacts,
        formats: tuple[StoredFormat, ...],
    ) -> dict[str, object]:
        """Build the safe metadata endpoint payload without report body text."""
        payload: dict[str, object] = {
            "report_id": str(report_id),
            "status": "completed",
            "available_formats": list(formats),
            "generation": cls._generation_metadata(artifacts),
        }
        if isinstance(artifacts, MultiDocumentPipelineArtifacts):
            payload["documents"] = [
                cls._document_metadata(document)
                for document in artifacts.source_documents
            ]
        else:
            payload["document"] = cls._document_metadata(artifacts.source_document)
        return payload

    @staticmethod
    def _document_metadata(document: ParsedDocument) -> dict[str, object]:
        return {
            "filename": document.filename,
            "file_type": document.file_type,
            "page_count": document.page_count,
            "word_count": document.word_count,
            "character_count": document.character_count,
        }
