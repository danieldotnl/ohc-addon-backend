"""Main FastAPI application file."""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ohc_backend.base_types import OHCServiceName
from ohc_backend.errors import AppError, ErrorCode
from ohc_backend.orchestrator import ServiceOrchestrator
from ohc_backend.routers import scripts
from ohc_backend.services.ha_service import HomeAssistantService
from ohc_backend.services.settings import Settings
from ohc_backend.utils.logging import configure_logging, log_error
from ohc_backend.utils.request_context import request_id_middleware

from .dependencies import deps
from .routers import automations

configure_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:  # noqa: ARG001
    """Application lifespan context manager."""
    try:
        logger.info("Initializing services.")
        data_folder = os.getenv("HA_DATA_FOLDER", "/data")
        settings = Settings(f"{data_folder}/config.json")

        orchestrator = ServiceOrchestrator()
        home_assistant = HomeAssistantService()
        orchestrator.register_service(OHCServiceName.SETTINGS, settings, requires_config=False)
        orchestrator.register_service(OHCServiceName.HOMEASSISTANT, home_assistant)

        await orchestrator.start()

        yield

        await orchestrator.stop()
    except Exception as e:
        if not isinstance(e, AppError):
            log_error(logger, "Critical startup error", e, critical=True)
            msg = "Application failed to start!"
            raise AppError(msg) from e
        raise
    finally:
        logger.info("Cleaning up application resources")
        await deps.cleanup()


app = FastAPI(lifespan=lifespan, debug=os.getenv("ENVIRONMENT") == "dev")
app.middleware("http")(request_id_middleware)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:  # noqa: ARG001
    """Handle application errors."""
    # No need to log here, already logged where the error occurred
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions."""
    log_error(logger, f"Unhandled exception in {request.method} {request.url.path}", exc, critical=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_code": ErrorCode.INTERNAL_ERROR,
            "message": "An unexpected error occurred",
            "details": {"type": type(exc).__name__},
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(
    automations.router,
    prefix="/api/automations",
    tags=["automations"],
)
app.include_router(
    scripts.router,
    prefix="/api/scripts",
    tags=["scripts"],
)
# app.include_router(
#     github.router,
#     prefix="/api/github",
#     tags=["github"],
# )


@app.get("/api/health")
async def health_check() -> dict:
    """Endpoint to check the health status of the application."""
    return {"status": "ok"}


# Mount frontend last (catches all other routes)
# Only serve frontend files in production
# if os.getenv("ENVIRONMENT") != "dev":
#     app.mount("/", StaticFiles(directory="../frontend/build",
#               html=True), name="frontend")
