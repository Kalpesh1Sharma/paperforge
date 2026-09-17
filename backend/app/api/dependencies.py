"""FastAPI dependency providers for replaceable PaperForge integrations."""

from fastapi import Depends

from app.config import Settings, settings
from app.integrations.superdocs import SuperDocsClient
from app.jobs import ReportJobReader, ReportJobService, SQLiteReportJobStore
from app.outlines import OutlineService
from app.projects import ProjectService, SQLiteProjectStore
from app.services.pipeline_service import PipelineService
from app.services.report_service import LocalReportStore, PaperForgeService
from app.services.review_service import ReviewService
from app.services.upload_service import UploadService


def get_settings() -> Settings:
    """Return the process configuration without exposing environment values."""
    return settings


def get_report_store(
    active_settings: Settings = Depends(get_settings),
) -> LocalReportStore:
    """Construct the local store selected by the current application settings."""
    return LocalReportStore(active_settings.report_storage_dir)


def get_upload_service(
    active_settings: Settings = Depends(get_settings),
) -> UploadService:
    """Reuse the existing streamed upload validator for report staging."""
    return UploadService(
        upload_dir=active_settings.report_storage_dir,
        max_upload_size_bytes=active_settings.max_upload_size_bytes,
    )


def get_project_service(
    store: LocalReportStore = Depends(get_report_store),
) -> ProjectService:
    """Provide durable local project state beside the report artifact store."""
    return ProjectService(
        SQLiteProjectStore(store.root_dir / "paperforge.db"),
        store.root_dir,
    )


def get_pipeline_service() -> PipelineService:
    """Provide the stateless, synchronous domain-pipeline adapter."""
    return PipelineService()


def get_paperforge_service(
    store: LocalReportStore = Depends(get_report_store),
    pipeline_service: PipelineService = Depends(get_pipeline_service),
    upload_service: UploadService = Depends(get_upload_service),
    project_service: ProjectService = Depends(get_project_service),
) -> PaperForgeService:
    """Provide a high-level service without constructing collaborators in routes."""
    return PaperForgeService(
        store=store,
        pipeline_service=pipeline_service,
        upload_service=upload_service,
        project_service=project_service,
    )


def get_report_job_store(
    store: LocalReportStore = Depends(get_report_store),
) -> SQLiteReportJobStore:
    """Provide the shared durable job store without initializing AI providers."""
    return SQLiteReportJobStore(store.root_dir / "paperforge.db")


def get_outline_service(
    store: LocalReportStore = Depends(get_report_store),
    upload_service: UploadService = Depends(get_upload_service),
) -> OutlineService:
    """Provide the durable evidence-outline planner and approval boundary."""
    return OutlineService(store.root_dir, upload_service)


def get_report_job_reader(
    job_store: SQLiteReportJobStore = Depends(get_report_job_store),
) -> ReportJobReader:
    """Provide lightweight job polling for the processing UI."""
    return ReportJobReader(job_store)


def get_report_job_service(
    report_service: PaperForgeService = Depends(get_paperforge_service),
    job_store: SQLiteReportJobStore = Depends(get_report_job_store),
) -> ReportJobService:
    """Provide report-job mutation and execution orchestration."""
    return ReportJobService(job_store, report_service)


def get_superdocs_client(
    active_settings: Settings = Depends(get_settings),
) -> SuperDocsClient:
    """Create the optional client lazily; missing configuration remains safe."""
    return SuperDocsClient(
        api_key=active_settings.superdocs_api_key,
        base_url=active_settings.superdocs_api_base_url,
    )


def get_review_service(
    store: LocalReportStore = Depends(get_report_store),
    client: SuperDocsClient = Depends(get_superdocs_client),
    active_settings: Settings = Depends(get_settings),
) -> ReviewService:
    """Provide a review orchestrator without affecting report generation DI."""
    return ReviewService(
        store=store,
        client=client,
        poll_interval_seconds=active_settings.superdocs_poll_interval_seconds,
        max_wait_seconds=active_settings.superdocs_max_wait_seconds,
    )
