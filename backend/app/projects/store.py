"""Small relational SQLite store for local PaperForge projects."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.projects.models import ProjectRecord, ProjectSource


class ProjectStoreError(RuntimeError):
    """Raised when SQLite cannot safely persist or retrieve project state."""


class SQLiteProjectStore:
    """Persist projects, sources, and formats with one connection per operation."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self._initialize()

    def create(self, project: ProjectRecord) -> ProjectRecord:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO projects
                        (id, title, report_id, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(project.id),
                        project.title,
                        str(project.report_id) if project.report_id else None,
                        project.status,
                        project.created_at.isoformat(),
                        project.updated_at.isoformat(),
                    ),
                )
                self._replace_children(connection, project)
        except sqlite3.Error as exc:
            raise ProjectStoreError("Unable to create the project record.") from exc
        return project

    def upsert(self, project: ProjectRecord) -> ProjectRecord:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO projects
                        (id, title, report_id, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,
                        report_id=excluded.report_id,
                        status=excluded.status,
                        updated_at=excluded.updated_at
                    """,
                    (
                        str(project.id),
                        project.title,
                        str(project.report_id) if project.report_id else None,
                        project.status,
                        project.created_at.isoformat(),
                        project.updated_at.isoformat(),
                    ),
                )
                self._replace_children(connection, project)
        except sqlite3.Error as exc:
            raise ProjectStoreError("Unable to persist the project record.") from exc
        return project

    def list(self) -> tuple[ProjectRecord, ...]:
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    "SELECT * FROM projects ORDER BY updated_at DESC, id ASC"
                ).fetchall()
                return tuple(self._record(connection, row) for row in rows)
        except (sqlite3.Error, ValueError) as exc:
            raise ProjectStoreError("Unable to read project records.") from exc

    def get(self, project_id: UUID) -> ProjectRecord | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT * FROM projects WHERE id = ?", (str(project_id),)
                ).fetchone()
                return self._record(connection, row) if row is not None else None
        except (sqlite3.Error, ValueError) as exc:
            raise ProjectStoreError("Unable to read the project record.") from exc

    def update_title(
        self, project_id: UUID, title: str, updated_at: datetime
    ) -> bool:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "UPDATE projects SET title = ?, updated_at = ? WHERE id = ?",
                    (title, updated_at.isoformat(), str(project_id)),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise ProjectStoreError("Unable to rename the project.") from exc

    def delete(self, project_id: UUID) -> bool:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM projects WHERE id = ?", (str(project_id),)
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise ProjectStoreError("Unable to delete the project.") from exc

    def metadata_value(self, key: str) -> str | None:
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT value FROM app_metadata WHERE key = ?", (key,)
                ).fetchone()
                return str(row["value"]) if row is not None else None
        except sqlite3.Error as exc:
            raise ProjectStoreError("Unable to read project-store metadata.") from exc

    def set_metadata(self, key: str, value: str) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO app_metadata (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (key, value),
                )
        except sqlite3.Error as exc:
            raise ProjectStoreError("Unable to persist project-store metadata.") from exc

    def _initialize(self) -> None:
        try:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS projects (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 100),
                        report_id TEXT UNIQUE,
                        status TEXT NOT NULL CHECK(status IN ('draft', 'ready')),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS project_sources (
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        position INTEGER NOT NULL,
                        filename TEXT NOT NULL,
                        file_type TEXT NOT NULL,
                        page_count INTEGER,
                        word_count INTEGER NOT NULL,
                        character_count INTEGER NOT NULL,
                        PRIMARY KEY (project_id, position)
                    );
                    CREATE TABLE IF NOT EXISTS project_formats (
                        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        position INTEGER NOT NULL,
                        format TEXT NOT NULL,
                        PRIMARY KEY (project_id, position)
                    );
                    CREATE TABLE IF NOT EXISTS app_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    """
                )
        except (OSError, sqlite3.Error) as exc:
            raise ProjectStoreError("Unable to initialize project storage.") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @staticmethod
    def _replace_children(
        connection: sqlite3.Connection, project: ProjectRecord
    ) -> None:
        project_id = str(project.id)
        connection.execute(
            "DELETE FROM project_sources WHERE project_id = ?", (project_id,)
        )
        connection.execute(
            "DELETE FROM project_formats WHERE project_id = ?", (project_id,)
        )
        connection.executemany(
            """
            INSERT INTO project_sources
                (project_id, position, filename, file_type, page_count,
                 word_count, character_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    project_id,
                    position,
                    source.filename,
                    source.file_type,
                    source.page_count,
                    source.word_count,
                    source.character_count,
                )
                for position, source in enumerate(project.sources)
            ),
        )
        connection.executemany(
            "INSERT INTO project_formats (project_id, position, format) VALUES (?, ?, ?)",
            (
                (project_id, position, format_name)
                for position, format_name in enumerate(project.available_formats)
            ),
        )

    @staticmethod
    def _record(connection: sqlite3.Connection, row: sqlite3.Row) -> ProjectRecord:
        source_rows = connection.execute(
            "SELECT * FROM project_sources WHERE project_id = ? ORDER BY position",
            (row["id"],),
        ).fetchall()
        format_rows = connection.execute(
            "SELECT format FROM project_formats WHERE project_id = ? ORDER BY position",
            (row["id"],),
        ).fetchall()
        return ProjectRecord(
            id=UUID(row["id"]),
            title=row["title"],
            report_id=UUID(row["report_id"]) if row["report_id"] else None,
            status=row["status"],
            sources=tuple(
                ProjectSource(
                    filename=item["filename"],
                    file_type=item["file_type"],
                    page_count=item["page_count"],
                    word_count=item["word_count"],
                    character_count=item["character_count"],
                )
                for item in source_rows
            ),
            available_formats=tuple(item["format"] for item in format_rows),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
