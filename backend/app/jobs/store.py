"""SQLite persistence for report-generation jobs."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

from app.jobs.models import ReportJobRecord


class ReportJobStoreError(RuntimeError):
    """Raised when job state cannot be persisted safely."""


class SQLiteReportJobStore:
    """Store one complete immutable job record per SQLite row."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._initialize()

    def create(self, job: ReportJobRecord) -> ReportJobRecord:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO report_jobs (job_id, payload) VALUES (?, ?)",
                    (str(job.job_id), job.model_dump_json()),
                )
        except sqlite3.Error as exc:
            raise ReportJobStoreError("Unable to create the report job.") from exc
        return job

    def upsert(self, job: ReportJobRecord) -> ReportJobRecord:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO report_jobs (job_id, payload) VALUES (?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET payload=excluded.payload
                    """,
                    (str(job.job_id), job.model_dump_json()),
                )
        except sqlite3.Error as exc:
            raise ReportJobStoreError("Unable to update the report job.") from exc
        return job

    def get(self, job_id: UUID) -> ReportJobRecord | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT payload FROM report_jobs WHERE job_id = ?",
                    (str(job_id),),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ReportJobStoreError("Unable to read the report job.") from exc
        if row is None:
            return None
        try:
            return ReportJobRecord.model_validate_json(row["payload"])
        except ValueError as exc:
            raise ReportJobStoreError("Stored report job state is invalid.") from exc

    def _initialize(self) -> None:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS report_jobs (
                        job_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL
                    )
                    """
                )
        except (OSError, sqlite3.Error) as exc:
            raise ReportJobStoreError("Unable to initialize report job storage.") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection
