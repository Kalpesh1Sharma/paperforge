"""Persistent background report-job coverage."""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app.api.dependencies import get_report_job_reader, get_report_job_service
from app.jobs import ReportJobService, SQLiteReportJobStore
from app.main import app
from app.services.pipeline_service import ProviderRateLimitedError
from app.services.report_service import StagedMultiReport, StagedReport


class _FakeReportService:
    def __init__(self, root: Path, *, fail: bool = False) -> None:
        self.root = root
        self.fail = fail
        self.finalized = False

    async def stage_report(self, uploaded_file: UploadFile) -> StagedReport:
        report_id = uuid4()
        directory = self.root / str(report_id)
        directory.mkdir(parents=True)
        path = directory / str(uploaded_file.filename)
        path.write_bytes(await uploaded_file.read())
        return StagedReport(report_id, path, str(uploaded_file.filename))

    async def stage_multi_report(
        self, uploaded_files: list[UploadFile]
    ) -> StagedMultiReport:
        report_id = uuid4()
        directory = self.root / str(report_id) / "sources"
        directory.mkdir(parents=True)
        filenames = tuple(str(item.filename) for item in uploaded_files)
        paths = tuple(directory / name for name in filenames)
        for item, path in zip(uploaded_files, paths, strict=True):
            path.write_bytes(await item.read())
        return StagedMultiReport(report_id, paths, filenames)

    def stage_regeneration(
        self, report_id: UUID
    ) -> tuple[StagedReport, None]:
        directory = self.root / str(uuid4())
        directory.mkdir(parents=True)
        path = directory / "evidence.pdf"
        path.write_bytes(b"%PDF regenerated")
        return StagedReport(UUID(directory.name), path, "evidence.pdf"), None

    def generate_report(self, path: Path, *args: object, **kwargs: object) -> object:
        del path, args
        return self._generate(kwargs)

    def generate_multi_report(
        self, paths: tuple[Path, ...], filenames: tuple[str, ...],
        *args: object, **kwargs: object,
    ) -> object:
        del paths, filenames, args
        return self._generate(kwargs)

    def _generate(self, kwargs: dict[str, object]) -> object:
        progress = kwargs["progress"]
        assert callable(progress)
        progress("extracting", 48, "Extracting grounded evidence")
        if self.fail:
            raise ProviderRateLimitedError("rate limited")
        progress("rendering", 93, "Rendering publication files")
        return SimpleNamespace(
            generation_metadata={"provider": "gemini", "fallback": False}
        )

    def finalize_staged_report(self, staged: StagedReport) -> None:
        del staged
        self.finalized = True


def _service(tmp_path: Path, *, fail: bool = False) -> tuple[ReportJobService, _FakeReportService]:
    report_service = _FakeReportService(tmp_path / "reports", fail=fail)
    service = ReportJobService(
        SQLiteReportJobStore(tmp_path / "paperforge.db"),
        report_service,  # type: ignore[arg-type]
    )
    return service, report_service


def test_job_state_survives_a_new_service_instance(tmp_path: Path) -> None:
    service, report_service = _service(tmp_path)
    upload = UploadFile(BytesIO(b"%PDF test"), filename="evidence.pdf")
    queued = asyncio.run(service.submit_report(upload, None))

    restored = ReportJobService(
        SQLiteReportJobStore(tmp_path / "paperforge.db"),
        report_service,  # type: ignore[arg-type]
    ).get(queued.job_id)
    assert restored.status == "queued"
    assert restored.source_filenames == ("evidence.pdf",)

    service.run(queued.job_id)
    completed = service.get(queued.job_id)
    assert completed.status == "completed"
    assert completed.stage == "completed"
    assert completed.progress == 100
    assert completed.provider == "gemini"
    assert completed.fallback is False
    assert report_service.finalized is True


def test_provider_exhaustion_becomes_a_safe_terminal_job(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, fail=True)
    upload = UploadFile(BytesIO(b"%PDF test"), filename="evidence.pdf")
    queued = asyncio.run(service.submit_report(upload, None))

    service.run(queued.job_id)
    failed = service.get(queued.job_id)
    assert failed.status == "failed"
    assert failed.stage == "failed"
    assert failed.error_code == "provider_rate_limited"
    assert "Every configured provider" in str(failed.error_message)


def test_job_api_returns_accepted_then_exposes_persisted_completion(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    app.dependency_overrides[get_report_job_service] = lambda: service
    app.dependency_overrides[get_report_job_reader] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/reports/jobs",
                files={"file": ("evidence.pdf", b"%PDF test", "application/pdf")},
            )
            assert response.status_code == 202
            body = response.json()
            assert body["status"] == "queued"
            assert "source_paths" not in body
            assert "settings_json" not in body

            status = client.get(f"/reports/jobs/{body['job_id']}")
            assert status.status_code == 200
            assert status.json()["status"] == "completed"
            assert status.json()["provider"] == "gemini"
    finally:
        app.dependency_overrides.clear()


def test_missing_job_is_a_sanitized_404(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    app.dependency_overrides[get_report_job_reader] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.get(f"/reports/jobs/{UUID(int=0)}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "report_job_not_found"
    finally:
        app.dependency_overrides.clear()


def test_regeneration_endpoint_starts_a_new_background_job(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    app.dependency_overrides[get_report_job_service] = lambda: service
    app.dependency_overrides[get_report_job_reader] = lambda: service
    original_id = uuid4()
    try:
        with TestClient(app) as client:
            response = client.post(f"/reports/{original_id}/regenerate")
            assert response.status_code == 202
            body = response.json()
            assert body["report_id"] != str(original_id)
            assert body["source_filenames"] == ["evidence.pdf"]
            completed = client.get(f"/reports/jobs/{body['job_id']}")
            assert completed.json()["status"] == "completed"
    finally:
        app.dependency_overrides.clear()
