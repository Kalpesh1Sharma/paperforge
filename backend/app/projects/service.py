"""Project lifecycle and migration orchestration."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from app.models.parsed_document import ParsedDocument
from app.projects.models import ProjectRecord, ProjectSource
from app.projects.store import ProjectStoreError, SQLiteProjectStore


class ProjectError(RuntimeError):
    """Base project-domain error."""


class ProjectNotFoundError(ProjectError):
    """Raised when the requested project does not exist."""


class ProjectConflictError(ProjectError):
    """Raised when a project cannot accept the requested association."""


class ProjectStorageError(ProjectError):
    """Raised when durable project state is unavailable."""


class ProjectValidationError(ProjectError):
    """Raised when project input is empty or outside accepted bounds."""


class ProjectService:
    """Manage projects and associate them with generated report artifacts."""

    _BACKFILL_KEY = "completed_report_backfill_v1"

    def __init__(self, store: SQLiteProjectStore, report_root: Path) -> None:
        self._store = store
        self._report_root = Path(report_root)
        self._backfill_completed_reports()

    def create(self, title: str) -> ProjectRecord:
        normalized = self._title(title)
        now = datetime.now(timezone.utc)
        record = ProjectRecord(
            id=uuid4(),
            title=normalized,
            report_id=None,
            status="draft",
            created_at=now,
            updated_at=now,
        )
        try:
            return self._store.create(record)
        except ProjectStoreError as exc:
            raise ProjectStorageError("The project could not be created.") from exc

    def list(self) -> tuple[ProjectRecord, ...]:
        try:
            return self._store.list()
        except ProjectStoreError as exc:
            raise ProjectStorageError("Projects could not be loaded.") from exc

    def get(self, project_id: UUID) -> ProjectRecord:
        try:
            record = self._store.get(project_id)
        except ProjectStoreError as exc:
            raise ProjectStorageError("The project could not be loaded.") from exc
        if record is None:
            raise ProjectNotFoundError("Project was not found.")
        return record

    def rename(self, project_id: UUID, title: str) -> ProjectRecord:
        normalized = self._title(title)
        try:
            updated = self._store.update_title(
                project_id, normalized, datetime.now(timezone.utc)
            )
        except ProjectStoreError as exc:
            raise ProjectStorageError("The project could not be renamed.") from exc
        if not updated:
            raise ProjectNotFoundError("Project was not found.")
        return self.get(project_id)

    def delete(self, project_id: UUID) -> None:
        record = self.get(project_id)
        try:
            deleted = self._store.delete(project_id)
            if deleted and record.report_id is not None:
                self._store.delete_report_jobs(record.report_id)
        except ProjectStoreError as exc:
            raise ProjectStorageError("The project could not be deleted.") from exc
        if not deleted:
            raise ProjectNotFoundError("Project was not found.")
        if record.report_id is not None:
            report_directory = self._report_root / str(record.report_id)
            try:
                if report_directory.is_dir():
                    shutil.rmtree(report_directory)
            except OSError as exc:
                raise ProjectStorageError(
                    "The project record was deleted, but its report files could not be cleaned up."
                ) from exc

    def attach_report(
        self,
        report_id: UUID,
        documents: tuple[ParsedDocument, ...],
        available_formats: tuple[str, ...],
        *,
        project_id: UUID | None = None,
        title: str | None = None,
    ) -> ProjectRecord:
        target_id = project_id or report_id
        existing = None
        try:
            existing = self._store.get(target_id)
        except ProjectStoreError as exc:
            raise ProjectStorageError("The project could not be loaded.") from exc
        if existing is not None and existing.report_id not in {None, report_id}:
            raise ProjectConflictError("Project is already associated with a report.")
        now = datetime.now(timezone.utc)
        record = ProjectRecord(
            id=target_id,
            title=(
                self._title(title)
                if title is not None
                else existing.title if existing else self._report_title(documents)
            ),
            report_id=report_id,
            status="ready",
            sources=tuple(self._source(document) for document in documents),
            available_formats=available_formats,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        try:
            return self._store.upsert(record)
        except ProjectStoreError as exc:
            raise ProjectStorageError("The report could not be associated with its project.") from exc

    def _backfill_completed_reports(self) -> None:
        try:
            if self._store.metadata_value(self._BACKFILL_KEY) == "complete":
                return
            if self._report_root.is_dir():
                for directory in self._report_root.iterdir():
                    self._backfill_directory(directory)
            self._store.set_metadata(self._BACKFILL_KEY, "complete")
        except (OSError, ProjectStoreError) as exc:
            raise ProjectStorageError("Existing reports could not be indexed.") from exc

    def _backfill_directory(self, directory: Path) -> None:
        try:
            report_id = UUID(directory.name)
        except (ValueError, AttributeError):
            return
        metadata_path = directory / "metadata.json"
        report_path = directory / "report.json"
        if not metadata_path.is_file() or not report_path.is_file():
            return
        if self._store.get(report_id) is not None:
            return
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            documents_payload = payload.get("documents") or [payload.get("document")]
            documents = tuple(
                ParsedDocument(
                    filename=item["filename"],
                    file_type=item["file_type"],
                    extracted_text="Stored report metadata.",
                    page_count=item.get("page_count"),
                    word_count=item["word_count"],
                    character_count=item["character_count"],
                    metadata={},
                )
                for item in documents_payload
                if isinstance(item, dict)
            )
            formats = tuple(str(item) for item in payload["available_formats"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return
        if documents:
            self.attach_report(report_id, documents, formats)

    @staticmethod
    def _source(document: ParsedDocument) -> ProjectSource:
        return ProjectSource(
            filename=document.filename,
            file_type=document.file_type,
            page_count=document.page_count,
            word_count=document.word_count,
            character_count=document.character_count,
        )

    @staticmethod
    def _title(value: str) -> str:
        normalized = " ".join(value.split()) if isinstance(value, str) else ""
        if not 1 <= len(normalized) <= 100:
            raise ProjectValidationError(
                "Project title must contain between 1 and 100 characters."
            )
        return normalized

    @classmethod
    def _report_title(cls, documents: tuple[ParsedDocument, ...]) -> str:
        if not documents:
            return "Untitled research report"
        stem = Path(documents[0].filename).stem.replace("-", " ").replace("_", " ")
        normalized = " ".join(stem.split()).title()
        return normalized[:100] or "Untitled research report"
