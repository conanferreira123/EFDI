"""
Application entrypoint.

Responsible for:
- Creating the FastAPI app instance
- Configuring logging
- Registering global exception handlers
- Configuring CORS
- Mounting routers (added incrementally in later phases)
- Exposing a /health endpoint for liveness/readiness checks
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.exceptions import EFDIException
from app.core.logging_config import setup_logging
from app.database.session import check_database_connection
from app.schemas.base import HealthCheckResponse

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Modern replacement for the deprecated on_event("startup"/"shutdown").
    Code before `yield` runs at startup; code after `yield` runs at
    shutdown.
    """
    logger.info("Starting %s [%s]", settings.APP_NAME, settings.APP_ENV)
    if check_database_connection():
        logger.info("Database connection verified.")
    else:
        logger.error("Database connection FAILED at startup. Check DATABASE_URL.")

    yield

    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Enterprise Accounts Payable (AP) and Record-to-Report (R2R) "
        "document intelligence platform: OCR extraction, classification, "
        "validation, approval workflow, and audit trail."
    ),
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Global exception handlers ---
@app.exception_handler(EFDIException)
async def efdi_exception_handler(request: Request, exc: EFDIException) -> JSONResponse:
    """
    Translate domain exceptions raised anywhere in services/repositories
    into a consistent JSON error shape, instead of letting FastAPI fall
    back to a generic 500.
    """
    logger.warning(
        "Handled exception on %s %s: %s", request.method, request.url.path, exc.message
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.__class__.__name__,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all for anything not explicitly handled. Logs full details
    server-side but returns a generic message to the client so internal
    errors (stack traces, query text, etc.) are never leaked.
    """
    logger.error(
        "Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred. Please contact support if this persists.",
            "details": {},
        },
    )


# --- Health check ---
@app.get("/health", response_model=HealthCheckResponse, tags=["System"])
async def health_check() -> HealthCheckResponse:
    """Liveness/readiness probe. Used by Docker, load balancers, and uptime checks."""
    db_ok = check_database_connection()
    return HealthCheckResponse(
        status="ok" if db_ok else "degraded",
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        database_connected=db_ok,
    )


@app.get("/", tags=["System"])
async def root() -> dict:
    return {
        "message": f"{settings.APP_NAME} API",
        "docs": "/api/docs",
        "health": "/health",
    }


# --- Routers ---
from app.routers import audit, auth, classification, documents, extraction, ocr, users, validation, workflow  # noqa: E402

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(documents.router, prefix=settings.API_V1_PREFIX)
app.include_router(ocr.router, prefix=settings.API_V1_PREFIX)
app.include_router(classification.router, prefix=settings.API_V1_PREFIX)
app.include_router(extraction.router, prefix=settings.API_V1_PREFIX)
app.include_router(validation.router, prefix=settings.API_V1_PREFIX)
app.include_router(workflow.router, prefix=settings.API_V1_PREFIX)
app.include_router(audit.router, prefix=settings.API_V1_PREFIX)
