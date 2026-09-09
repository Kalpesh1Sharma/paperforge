"""Background report-generation orchestration with persistent progress."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile

from app.jobs.models import ReportJobRecord
from app.jobs.store import ReportJobStoreError, SQLiteReportJobStore
from app.reports import ReportGenerationSettings
from app.services.pipeline_service import (
    InvalidDocumentError,
    ProviderRateLimitedError,
    TemporaryProviderUnavailableError,
)
from app.services.report_service import (
    PaperForgeService,
    ReportOutputError,
    ReportStorageError,
    StagedReport,
    StagedMultiReport,
)

logger = logging.getLogger(__name__)


class ReportJobError(RuntimeError):
    """Base report-job domain error."""


class ReportJobNotFoundError(ReportJobError):
    """Raised when a requested job does not exist."""


class ReportJobStorageError(ReportJobError):
    """Raised when persistent job state is unavailable."""


class ReportJobReader:
    """Read durable job progress without constructing the AI pipeline."""

    def __init__(self, store: SQLiteReportJobStore) -> None:
        self._store = store

    def get(self, job_id: UUID) -> ReportJobRecord:
        try:
            job = self._store.get(job_id)
        except ReportJobStoreError as exc:
            raise ReportJobStorageError("Report progress could not be loaded.") from exc
        if job is None:
            raise ReportJobNotFoundError("Report job was not found.")
        return job


class ReportJobService(ReportJobReader):
    """Stage uploads, run reports off-request, and expose durable progress."""

    def __init__(
        self,
        store: SQLiteReportJobStore,
        report_service: PaperForgeService,
    ) -> None:
        super().__init__(store)
        self._report_service = report_service

    async def submit_report(
        self,
        uploaded_file: UploadFile,
        settings: ReportGenerationSettings | None,
    ) -> ReportJobRecord:
        staged = await self._report_service.stage_report(uploaded_file)
        return self._create_job(
            report_id=staged.report_id,
            source_paths=(str(staged.processing_path),),
            source_filenames=(staged.source_filename,),
            settings=settings,
        )

    async def submit_multi_report(
        self,
        uploaded_files: list[UploadFile],
        settings: ReportGenerationSettings | None,
    ) -> ReportJobRecord:
        staged = await self._report_service.stage_multi_report(uploaded_files)
        return self._create_job(
            report_id=staged.report_id,
            source_paths=tuple(str(path) for path in staged.source_paths),
            source_filenames=staged.source_filenames,
            settings=settings,
        )

    def submit_regeneration(self, report_id: UUID) -> ReportJobRecord:
        """Start a new version-like report from one completed report's sources."""
        staged, settings = self._report_service.stage_regeneration(report_id)
        if isinstance(staged, StagedReport):
            return self._create_job(
                report_id=staged.report_id,
                source_paths=(str(staged.processing_path),),
                source_filenames=(staged.source_filename,),
                settings=settings,
            )
        if isinstance(staged, StagedMultiReport):
            return self._create_job(
                report_id=staged.report_id,
                source_paths=tuple(str(path) for path in staged.source_paths),
                source_filenames=staged.source_filenames,
                settings=settings,
            )
        raise ReportJobStorageError("The report sources could not be staged.")

    def run(self, job_id: UUID) -> None:
        """Execute one queued job idempotently in a background thread."""
        job = self.get(job_id)
        if job.status in {"completed", "failed"}:
            return
        self._save(
            job.model_copy(
                update={
                    "status": "running",
                    "stage": "parsing",
                    "progress": 12,
                    "message": "Starting document processing",
                    "updated_at": self._now(),
                }
            )
        )
        def progress(stage: str, percent: int, message: str) -> None:
            current = self.get(job_id)
            self._save(
                current.model_copy(
                    update={
                        "status": "running",
                        "stage": stage,
                        "progress": max(current.progress, percent),
                        "message": message,
                        "updated_at": self._now(),
                    }
                )
            )

        try:
            settings = (
                ReportGenerationSettings.model_validate_json(job.settings_json)
                if job.settings_json is not None
                else None
            )
            paths = tuple(Path(value) for value in job.source_paths)
            if len(paths) == 1:
                result = self._report_service.generate_report(
                    paths[0],
                    "all",
                    report_id=job.report_id,
                    settings=settings,
                    progress=progress,
                )
            else:
                result = self._report_service.generate_multi_report(
                    paths,
                    job.source_filenames,
                    "all",
                    report_id=job.report_id,
                    settings=settings,
                    progress=progress,
                )
        except InvalidDocumentError:
            self._fail(job_id, "invalid_document", "A source PDF could not be read.")
            return
        except ProviderRateLimitedError:
            self._fail(
                job_id,
                "provider_rate_limited",
                "Every configured provider was rate limited and generation stopped.",
            )
            return
        except TemporaryProviderUnavailableError:
            self._fail(
                job_id,
                "provider_unavailable",
                "Every configured provider was unavailable and generation stopped.",
            )
            return
        except (ReportOutputError, ReportStorageError):
            self._fail(
                job_id,
                "report_storage_failure",
                "The report output could not be safely stored.",
            )
            return
        except Exception:
            logger.exception("Unexpected report job failure | job_id=%s", job_id)
            self._fail(
                job_id,
                "generation_failed",
                "PaperForge could not complete this report.",
            )
            return
        finally:
            if len(job.source_paths) == 1:
                self._finalize_single_source(job)

        final = self.get(job_id)
        generation = result.generation_metadata
        now = self._now()
        self._save(
            final.model_copy(
                update={
                    "status": "completed",
                    "stage": "completed",
                    "progress": 100,
                    "message": "Your report is ready",
                    "provider": str(generation["provider"]),
                    "fallback": bool(generation["fallback"]),
                    "updated_at": now,
                    "completed_at": now,
                }
            )
        )

    def _create_job(
        self,
        *,
        report_id: UUID,
        source_paths: tuple[str, ...],
        source_filenames: tuple[str, ...],
        settings: ReportGenerationSettings | None,
    ) -> ReportJobRecord:
        now = self._now()
        job = ReportJobRecord(
            job_id=uuid4(),
            report_id=report_id,
            status="queued",
            stage="queued",
            progress=8,
            message="Sources uploaded; waiting to start",
            source_paths=source_paths,
            source_filenames=source_filenames,
            settings_json=settings.model_dump_json() if settings is not None else None,
            created_at=now,
            updated_at=now,
        )
        try:
            return self._store.create(job)
        except ReportJobStoreError as exc:
            raise ReportJobStorageError("The report job could not be created.") from exc

    def _save(self, job: ReportJobRecord) -> ReportJobRecord:
        try:
            return self._store.upsert(job)
        except ReportJobStoreError as exc:
            raise ReportJobStorageError("Report progress could not be saved.") from exc

    def _fail(self, job_id: UUID, code: str, message: str) -> None:
        current = self.get(job_id)
        now = self._now()
        self._save(
            current.model_copy(
                update={
                    "status": "failed",
                    "stage": "failed",
                    "message": message,
                    "error_code": code,
                    "error_message": message,
                    "updated_at": now,
                    "completed_at": now,
                }
            )
        )

    def _finalize_single_source(self, job: ReportJobRecord) -> None:
        staged = StagedReport(
            report_id=job.report_id,
            processing_path=Path(job.source_paths[0]),
            source_filename=job.source_filenames[0],
        )
        try:
            self._report_service.finalize_staged_report(staged)
        except ReportStorageError:
            logger.exception("Unable to finalize job source | job_id=%s", job.job_id)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
