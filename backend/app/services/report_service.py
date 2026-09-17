"""Local report storage and high-level synchronous service orchestration."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Literal
from uuid import UUID, uuid4

from fastapi import UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.models.parsed_document import ParsedDocument
from app.projects import ProjectService, SQLiteProjectStore
from app.reports import (
    DocumentMetadata,
    EditableDocxRenderer,
    HTMLRenderer,
    MarkdownRenderer,
    PDFRenderer,
    PRESENTATION_SECTION_SPECS,
    PresentationModel,
    PresentationSection,
    ReportGenerationSettings,
    TableOfContents,
    TableOfContentsEntry,
)
from app.reports.exceptions import ReportRenderingError
from app.reports.publication_metadata import document_overview_intro
from app.reports.citation_styles import apply_citation_style
from app.reports.quality import check_report_quality
from app.reports.editor import (
    SectionTransformer,
    TransformAction,
    editable_section_text,
)
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

ReportFormat = Literal["all", "json", "html", "markdown", "pdf", "docx"]
StoredFormat = Literal["json", "html", "markdown", "pdf", "docx"]
_AVAILABLE_FORMATS: tuple[StoredFormat, ...] = ("json", "html", "markdown", "pdf", "docx")


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


class ReportEditConflictError(ReportServiceError):
    """Raised when a locked section rejects a content mutation."""


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


@dataclass(frozen=True, slots=True)
class StagedReport:
    """One validated source stored before background generation begins."""

    report_id: UUID
    processing_path: Path
    source_filename: str


@dataclass(frozen=True, slots=True)
class StagedMultiReport:
    """Validated ordered sources stored before background generation begins."""

    report_id: UUID
    source_paths: tuple[Path, ...]
    source_filenames: tuple[str, ...]


ProgressCallback = Callable[[str, int, str], None]


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
            "report.docx",
            "metadata.json",
            "review.json",
            "reviewed_report.docx",
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

    def write_bytes(self, report_id: UUID, artifact_name: str, value: bytes) -> Path:
        """Atomically persist one approved binary review artifact."""
        if not isinstance(value, bytes):
            raise ReportStorageError("Binary report artifacts must be bytes.")
        destination = self.artifact_path(report_id, artifact_name)
        self._write_bytes(destination, value)
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

    def prepare_uploaded_input(
        self, report_id: UUID, temporary_path: Path, filename: str
    ) -> Path:
        """Restore a safe display filename while the report is being parsed."""
        if Path(filename).name != filename or filename in {"", ".", ".."}:
            raise ReportStorageError("Uploaded source filename is invalid.")
        source = Path(temporary_path)
        destination = self.report_directory(report_id) / filename
        try:
            source.replace(destination)
        except OSError as exc:
            raise ReportStorageError("Unable to prepare the uploaded PDF.") from exc
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
        docx_renderer: EditableDocxRenderer | None = None,
        project_service: ProjectService | None = None,
        section_transformer: SectionTransformer | None = None,
    ) -> None:
        self._store = store
        self._pipeline_service = pipeline_service
        self._upload_service = upload_service
        self._markdown_renderer = markdown_renderer or MarkdownRenderer()
        self._html_renderer = html_renderer or HTMLRenderer()
        self._pdf_renderer = pdf_renderer or PDFRenderer()
        self._docx_renderer = docx_renderer or EditableDocxRenderer()
        self._section_transformer = section_transformer or SectionTransformer()
        self._project_service = project_service or ProjectService(
            SQLiteProjectStore(store.root_dir / "paperforge.db"),
            store.root_dir,
        )

    async def create_report(
        self,
        uploaded_file: UploadFile,
        settings: ReportGenerationSettings | None = None,
    ) -> GeneratedReport:
        """Stream one PDF upload into local storage, then generate all formats."""
        staged = await self.stage_report(uploaded_file)
        try:
            return await run_in_threadpool(
                self.generate_report,
                staged.processing_path,
                "all",
                report_id=staged.report_id,
                settings=settings,
            )
        finally:
            self.finalize_staged_report(staged)

    async def create_multi_report(
        self,
        uploaded_files: list[UploadFile],
        settings: ReportGenerationSettings | None = None,
    ) -> GeneratedMultiReport:
        """Stage 2–5 PDFs, then run one ordered combined pipeline in a worker."""
        staged = await self.stage_multi_report(uploaded_files)
        return await run_in_threadpool(
            self.generate_multi_report,
            staged.source_paths,
            staged.source_filenames,
            "all",
            report_id=staged.report_id,
            settings=settings,
        )

    async def stage_report(self, uploaded_file: UploadFile) -> StagedReport:
        """Persist one upload so request-owned file handles can close immediately."""
        filename = self._validate_pdf_upload(uploaded_file)
        report_id = uuid4()
        try:
            upload_response = await self._upload_service.save_files(
                [uploaded_file], report_id
            )
        except UnsupportedFileTypeError as exc:
            raise InvalidReportUploadError("Only PDF uploads are accepted.") from exc
        except (UploadTooLargeError, UploadValidationError) as exc:
            raise InvalidReportUploadError(str(exc)) from exc
        except UploadStorageError as exc:
            raise ReportStorageError("Unable to persist the uploaded PDF.") from exc
        temporary_path = self._store.report_directory(report_id) / f"001_{filename}"
        processing_path = self._store.prepare_uploaded_input(
            report_id, temporary_path, filename
        )
        return StagedReport(
            report_id=report_id,
            processing_path=processing_path,
            source_filename=filename,
        )

    async def stage_multi_report(
        self, uploaded_files: list[UploadFile]
    ) -> StagedMultiReport:
        """Persist ordered uploads before starting a background worker."""
        if not 2 <= len(uploaded_files) <= 5:
            raise InvalidReportUploadError("Provide between 2 and 5 PDF files.")
        filenames = tuple(self._validate_pdf_upload(file) for file in uploaded_files)
        if len({name.casefold() for name in filenames}) != len(filenames):
            raise InvalidReportUploadError("Uploaded PDF filenames must be unique.")
        report_id = uuid4()
        try:
            upload_response = await self._upload_service.save_files(
                uploaded_files, report_id
            )
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
        return StagedMultiReport(
            report_id=report_id,
            source_paths=source_paths,
            source_filenames=filenames,
        )

    def finalize_staged_report(self, staged: StagedReport) -> None:
        """Move a single staged source to its canonical durable input path."""
        if staged.processing_path.exists():
            self._store.finalize_uploaded_input(
                staged.report_id, staged.processing_path
            )

    def stage_regeneration(
        self, report_id: UUID
    ) -> tuple[StagedReport | StagedMultiReport, ReportGenerationSettings | None]:
        """Copy persisted sources into a new report without mutating the original."""
        metadata = self.metadata(report_id)
        settings_payload = metadata.get("settings")
        try:
            generation_settings = (
                ReportGenerationSettings.model_validate_json(
                    json.dumps(settings_payload)
                )
                if settings_payload is not None
                else None
            )
        except (ValidationError, ValueError) as exc:
            raise ReportStorageError("Stored report settings are invalid.") from exc

        document_payloads = metadata.get("documents")
        if document_payloads is None:
            document_payload = metadata.get("document")
            document_payloads = [document_payload] if document_payload is not None else []
        if not isinstance(document_payloads, list) or not document_payloads:
            raise ReportStorageError("Stored report source metadata is invalid.")
        filenames = tuple(
            self._stored_source_filename(document) for document in document_payloads
        )

        new_report_id = uuid4()
        directory = self._store.ensure_report_directory(new_report_id)
        try:
            if len(filenames) == 1:
                source = self._store.input_path(report_id)
                if not source.is_file():
                    raise ReportNotFoundError("The original report source is unavailable.")
                processing_path = directory / filenames[0]
                shutil.copyfile(source, processing_path)
                return (
                    StagedReport(new_report_id, processing_path, filenames[0]),
                    generation_settings,
                )

            source_directory = self._store.report_directory(report_id) / "sources"
            source_paths = tuple(sorted(source_directory.glob("[0-9][0-9][0-9]_*")))
            if len(source_paths) != len(filenames) or not all(path.is_file() for path in source_paths):
                raise ReportNotFoundError("The original report sources are unavailable.")
            destination_directory = directory / "sources"
            destination_directory.mkdir()
            destinations = tuple(
                destination_directory / f"{index:03d}_{filename}"
                for index, filename in enumerate(filenames, start=1)
            )
            for source, destination in zip(source_paths, destinations, strict=True):
                shutil.copyfile(source, destination)
            return (
                StagedMultiReport(new_report_id, destinations, filenames),
                generation_settings,
            )
        except (ReportNotFoundError, ReportStorageError):
            shutil.rmtree(directory, ignore_errors=True)
            raise
        except OSError as exc:
            shutil.rmtree(directory, ignore_errors=True)
            raise ReportStorageError("Unable to stage report regeneration.") from exc

    def generate_report(
        self,
        uploaded_file: Path,
        output_format: ReportFormat = "all",
        *,
        report_id: UUID | None = None,
        settings: ReportGenerationSettings | None = None,
        progress: ProgressCallback | None = None,
    ) -> GeneratedReport:
        """Run the full synchronous pipeline for one already-persisted PDF.

        ``output_format`` permits focused service callers while the HTTP upload
        endpoint intentionally requests ``all`` so every retrieval endpoint is
        ready immediately after a successful POST.
        """
        if output_format not in {"all", "json", "html", "markdown", "pdf", "docx"}:
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

        artifacts = (
            self._pipeline_service.process(path, progress=progress)
            if settings is None
            else self._pipeline_service.process(
                path, mode=settings.structure, progress=progress
            )
        )
        artifacts = self._apply_generation_settings(artifacts, settings)
        if progress is not None:
            progress("rendering", 93, "Rendering and saving report formats")
        formats = self._materialize_artifacts(
            active_report_id,
            artifacts,
            output_format,
            settings,
        )
        result = GeneratedReport(
            report_id=active_report_id,
            available_formats=formats,
            source_document=artifacts.source_document,
            generation_metadata=self._generation_metadata(artifacts),
        )
        self._project_service.attach_report(
            result.report_id,
            (result.source_document,),
            result.available_formats,
            title=settings.project_title if settings is not None else None,
        )
        return result

    def generate_multi_report(
        self,
        source_paths: tuple[Path, ...],
        source_filenames: tuple[str, ...],
        output_format: ReportFormat = "all",
        *,
        report_id: UUID,
        settings: ReportGenerationSettings | None = None,
        progress: ProgressCallback | None = None,
    ) -> GeneratedMultiReport:
        """Run one combined pipeline over already-persisted ordered PDFs."""
        if output_format not in {"all", "json", "html", "markdown", "pdf", "docx"}:
            raise InvalidReportUploadError("Requested output format is not supported.")
        artifacts = (
            self._pipeline_service.process_many(
                source_paths, source_filenames, progress=progress
            )
            if settings is None
            else self._pipeline_service.process_many(
                source_paths,
                source_filenames,
                mode=settings.structure,
                progress=progress,
            )
        )
        artifacts = self._apply_generation_settings(artifacts, settings)
        if progress is not None:
            progress("rendering", 93, "Rendering and saving report formats")
        formats = self._materialize_artifacts(
            report_id, artifacts, output_format, settings
        )
        result = GeneratedMultiReport(
            report_id=report_id,
            available_formats=formats,
            source_documents=artifacts.source_documents,
            generation_metadata=self._generation_metadata(artifacts),
        )
        self._project_service.attach_report(
            result.report_id,
            result.source_documents,
            result.available_formats,
            title=settings.project_title if settings is not None else None,
        )
        return result

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

    def docx_path(self, report_id: UUID) -> Path:
        """Return the locally generated, fully editable Word report."""
        return self._store.file_path(report_id, "report.docx")

    def editing_state(self, report_id: UUID) -> dict[str, object]:
        """Return editable section buffers without exposing hidden report data."""
        presentation = self.presentation(report_id)
        return self._editing_payload(presentation)

    def update_section(
        self,
        report_id: UUID,
        section_key: str,
        content: str,
    ) -> dict[str, object]:
        """Replace one unlocked section body and rerender existing artifacts."""
        presentation = self.presentation(report_id)
        index, section = self._editable_section(presentation, section_key)
        if section.locked:
            raise ReportEditConflictError(
                "Unlock this section before changing its content."
            )
        normalized_content = content.strip()
        if not normalized_content:
            raise InvalidReportUploadError("Section content must not be blank.")
        updated = section.model_copy(update={"edited_content": normalized_content})
        presentation = self._replace_section(presentation, index, updated)
        self._persist_edited_presentation(report_id, presentation)
        return self._editing_payload(presentation)

    def transform_section(
        self,
        report_id: UUID,
        section_key: str,
        action: TransformAction,
    ) -> dict[str, object]:
        """Rewrite one unlocked section through BYOK failover and save the result."""
        presentation = self.presentation(report_id)
        index, section = self._editable_section(presentation, section_key)
        if section.locked:
            raise ReportEditConflictError(
                "Unlock this section before changing its content."
            )
        result = self._section_transformer.transform(
            editable_section_text(section),
            action,
            heading=section.heading,
        )
        normalized_content = result.content.strip()
        if not normalized_content:
            raise InvalidReportUploadError(
                "The assisted edit did not return usable section content."
            )
        updated = section.model_copy(update={"edited_content": normalized_content})
        presentation = self._replace_section(presentation, index, updated)
        self._persist_edited_presentation(report_id, presentation)
        payload = self._editing_payload(presentation)
        payload["last_transform"] = {
            "action": action,
            "provider": result.provider,
            "fallback": result.fallback,
        }
        return payload

    def set_section_lock(
        self,
        report_id: UUID,
        section_key: str,
        locked: bool,
    ) -> dict[str, object]:
        """Persist explicit approval state without modifying section content."""
        presentation = self.presentation(report_id)
        index, section = self._editable_section(presentation, section_key)
        updated = section.model_copy(update={"locked": locked})
        presentation = self._replace_section(presentation, index, updated)
        self._persist_edited_presentation(report_id, presentation)
        return self._editing_payload(presentation)

    def switch_template(
        self,
        report_id: UUID,
        template_key: str,
    ) -> dict[str, object]:
        """Rerender the same saved content with another registered template."""
        if template_key not in {
            "paperforge-classic",
            "modern-research",
            "ieee-inspired-technical",
        }:
            raise InvalidReportUploadError("Choose a supported Phase 2 template.")
        current = self.presentation(report_id)
        presentation = current.model_copy(
            update={
                "template_key": template_key,
                "revision": current.revision + 1,
            }
        )
        metadata = self.metadata(report_id)
        settings_payload = metadata.get("settings")
        if isinstance(settings_payload, dict):
            visual_theme = settings_payload.get("visual_theme")
            if isinstance(visual_theme, dict):
                visual_theme = dict(visual_theme)
                visual_theme["template"] = template_key
                settings_payload = dict(settings_payload)
                settings_payload["visual_theme"] = visual_theme
                metadata["settings"] = settings_payload
        self._persist_edited_presentation(report_id, presentation, metadata=metadata)
        return self._editing_payload(presentation)

    @staticmethod
    def _editable_section(
        presentation: PresentationModel,
        section_key: str,
    ) -> tuple[int, PresentationSection]:
        for index, section in enumerate(presentation.sections):
            if section.key == section_key:
                return index, section
        raise InvalidReportUploadError("That report section is not available.")

    @staticmethod
    def _replace_section(
        presentation: PresentationModel,
        index: int,
        section: PresentationSection,
    ) -> PresentationModel:
        sections = list(presentation.sections)
        sections[index] = section
        return presentation.model_copy(
            update={
                "sections": tuple(sections),
                "revision": presentation.revision + 1,
            }
        )

    @staticmethod
    def _editing_payload(presentation: PresentationModel) -> dict[str, object]:
        return {
            "template_key": presentation.template_key,
            "revision": presentation.revision,
            "sections": [
                {
                    "key": section.key,
                    "heading": section.heading,
                    "content": editable_section_text(section),
                    "locked": section.locked,
                    "edited": section.edited_content is not None,
                }
                for section in presentation.sections
            ],
            "last_transform": None,
        }

    def _persist_edited_presentation(
        self,
        report_id: UUID,
        presentation: PresentationModel,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Render every derivative first, then replace the stored publication."""
        presentation = check_report_quality(
            presentation,
            bibliography_required=bool(presentation.bibliography),
        )
        directory = self._store.report_directory(report_id)
        temporary_pdf: Path | None = None
        temporary_docx: Path | None = None
        try:
            markdown = self._markdown_renderer.render_presentation(presentation)
            html = self._html_renderer.render_presentation(presentation)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".edited-report-", suffix=".pdf", dir=directory
            )
            os.close(descriptor)
            temporary_pdf = Path(temporary_name)
            self._pdf_renderer.render_presentation(presentation, temporary_pdf)
            pdf_bytes = temporary_pdf.read_bytes()
            descriptor, temporary_docx_name = tempfile.mkstemp(
                prefix=".edited-report-", suffix=".docx", dir=directory
            )
            os.close(descriptor)
            temporary_docx = Path(temporary_docx_name)
            self._docx_renderer.render_presentation(presentation, temporary_docx)
            docx_bytes = temporary_docx.read_bytes()
            self._store.write_text(report_id, "report.md", markdown)
            self._store.write_text(report_id, "report.html", html)
            self._store.write_bytes(report_id, "report.pdf", pdf_bytes)
            self._store.write_bytes(report_id, "report.docx", docx_bytes)
            if metadata is not None:
                self._store.write_json(report_id, "metadata.json", metadata)
            self._store.write_json(
                report_id,
                "report.json",
                presentation.model_dump(mode="json", warnings="error"),
            )
        except ReportRenderingError as exc:
            raise ReportOutputError("Unable to render the edited report output.") from exc
        except ReportStorageError:
            raise
        except OSError as exc:
            raise ReportStorageError("Unable to persist edited report artifacts.") from exc
        finally:
            if temporary_pdf is not None:
                temporary_pdf.unlink(missing_ok=True)
            if temporary_docx is not None:
                temporary_docx.unlink(missing_ok=True)

    def _materialize_artifacts(
        self,
        report_id: UUID,
        artifacts: PipelineArtifacts | MultiDocumentPipelineArtifacts,
        output_format: ReportFormat,
        settings: ReportGenerationSettings | None = None,
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
            if "docx" in formats:
                self._docx_renderer.render_presentation(
                    artifacts.presentation,
                    self._store.artifact_path(report_id, "report.docx"),
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
                self._metadata_payload(report_id, artifacts, formats, settings),
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
    def _stored_source_filename(payload: object) -> str:
        if not isinstance(payload, dict):
            raise ReportStorageError("Stored report source metadata is invalid.")
        filename = payload.get("filename")
        if not isinstance(filename, str):
            raise ReportStorageError("Stored report source metadata is invalid.")
        safe_filename = Path(filename.replace("\\", "/")).name
        if safe_filename != filename or Path(safe_filename).suffix.lower() != ".pdf":
            raise ReportStorageError("Stored report source metadata is invalid.")
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
        settings: ReportGenerationSettings | None = None,
    ) -> dict[str, object]:
        """Build the safe metadata endpoint payload without report body text."""
        payload: dict[str, object] = {
            "report_id": str(report_id),
            "status": "completed",
            "available_formats": list(formats),
            "generation": cls._generation_metadata(artifacts),
        }
        if settings is not None:
            payload["settings"] = settings.model_dump(mode="json")
        if isinstance(artifacts, MultiDocumentPipelineArtifacts):
            payload["documents"] = [
                cls._document_metadata(document)
                for document in artifacts.source_documents
            ]
        else:
            payload["document"] = cls._document_metadata(artifacts.source_document)
        return payload

    @staticmethod
    def _apply_generation_settings(
        artifacts: PipelineArtifacts | MultiDocumentPipelineArtifacts,
        settings: ReportGenerationSettings | None,
    ) -> PipelineArtifacts | MultiDocumentPipelineArtifacts:
        """Apply publication metadata without modifying evidence or report text."""
        if settings is None:
            presentation = apply_citation_style(
                artifacts.presentation,
                style="source-linked",
                include_bibliography=True,
            )
            presentation = check_report_quality(
                presentation, bibliography_required=True
            )
            return replace(artifacts, presentation=presentation)
        cover_payload = artifacts.presentation.cover.model_dump(mode="python")
        cover_payload.update(
            {
                "title": settings.report_title,
                "domain": settings.research_domain,
                "author": settings.author,
                "organisation": settings.organisation,
                "subtitle": settings.publication.subtitle,
                "university": settings.publication.university,
                "department": settings.publication.department,
                "publication_type": settings.publication.publication_type,
            }
        )
        cover = DocumentMetadata.model_validate(cover_payload)
        composed_sections = {
            section.key: section for section in artifacts.presentation.sections
        }
        canonical_anchors = {
            key: anchor_id
            for key, _heading, anchor_id in PRESENTATION_SECTION_SPECS
        }
        sections = tuple(
            composed_sections.get(
                configured.key,
                PresentationSection(
                    key=configured.key,
                    heading=configured.heading,
                    anchor_id=canonical_anchors[configured.key],
                ),
            ).model_copy(
                update={
                    "heading": configured.heading,
                    **(
                        {"intro": document_overview_intro(cover)}
                        if configured.key == "document-overview"
                        else {}
                    ),
                }
            )
            for configured in settings.report_structure.sections
        )
        table_of_contents = TableOfContents(
            entries=tuple(
                TableOfContentsEntry(
                    heading=section.heading,
                    anchor_id=section.anchor_id,
                )
                for section in sections
            )
        )
        presentation = artifacts.presentation.model_copy(
            update={
                "cover": cover,
                "sections": sections,
                "table_of_contents": table_of_contents,
                "template_key": settings.visual_template,
                "page_size": settings.visual_theme.page_size,
                "content_density": settings.visual_theme.density,
                "accent_color": settings.visual_theme.accent_color,
                "citation_style": settings.citations.style,
            }
        )
        presentation = apply_citation_style(
            presentation,
            style=settings.citations.style,
            include_bibliography=settings.citations.include_bibliography,
        )
        presentation = check_report_quality(
            presentation,
            bibliography_required=settings.citations.include_bibliography,
        )
        return replace(artifacts, presentation=presentation)

    @staticmethod
    def _document_metadata(document: ParsedDocument) -> dict[str, object]:
        return {
            "filename": document.filename,
            "file_type": document.file_type,
            "page_count": document.page_count,
            "word_count": document.word_count,
            "character_count": document.character_count,
        }
