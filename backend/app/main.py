import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.routes.health import router as health_router
from app.api.routes.reports import router as reports_router
from app.api.routes.upload import router as upload_router
from app.config import settings


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Synchronous API for generating deterministic PaperForge research "
        "reports from uploaded PDF documents."
    ),
    openapi_tags=[
        {"name": "Health", "description": "Service readiness endpoints."},
        {"name": "Reports", "description": "Report generation and retrieval."},
        {"name": "Upload", "description": "Temporary research-file uploads."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next) -> Response:
    """Attach one request ID and log safe request-level operational telemetry."""
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.request_id = request_id
    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger = logging.getLogger(__name__)
        logger.exception(
            "HTTP request completed | request_id=%s | method=%s | path=%s | "
            "elapsed_ms=%.2f | outcome=failure",
            request_id,
            request.method,
            request.url.path,
            (perf_counter() - started_at) * 1000,
        )
        raise

    response.headers["X-Request-ID"] = request_id
    logging.getLogger(__name__).info(
        "HTTP request completed | request_id=%s | method=%s | path=%s | "
        "status=%s | elapsed_ms=%.2f | outcome=%s",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        (perf_counter() - started_at) * 1000,
        "success" if response.status_code < 400 else "failure",
    )
    return response


install_error_handlers(app)

app.include_router(health_router)
app.include_router(reports_router)
app.include_router(upload_router)
