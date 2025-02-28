"""Main FastAPI application file."""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ohc_backend.errors import AppError, ErrorCode
from ohc_backend.services.github.errors import GitHubAuthError
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
        logger.info("Initializing application dependencies")
        await deps.async_init()

        try:
            logger.info("Setting up GitHub integration")
            await deps.setup_github()
        except TimeoutError as e:
            msg = "GitHub authentication timed out. Please restart the add-on to try again."
            log_error(logger, msg, e, critical=True)
            raise AppError(message=msg, status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                           error_code=ErrorCode.AUTHENTICATION_FAILED) from e
        except GitHubAuthError as e:
            msg = "Failed to authenticate with GitHub"
            log_error(logger, msg, e, critical=True)
            raise AppError(message=msg, status_code=status.HTTP_401_UNAUTHORIZED,
                           error_code=ErrorCode.AUTHENTICATION_FAILED) from e
        except Exception as e:
            msg = f"Failed to set up GitHub integration: {e}"
            log_error(logger, msg, e, critical=True)
            raise AppError(message=msg, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                           error_code=ErrorCode.GITHUB_API_ERROR) from e

        try:
            logger.info("Starting sync manager")
            sync_manager = deps.get_sync_manager()
            await sync_manager.start()
            logger.info("Application started successfully")
            yield
        except Exception as e:
            log_error(logger, "Error starting sync manager", e, critical=True)
            raise AppError(
                message=f"Sync manager failed to start: {e!s}", error_code=ErrorCode.SYNC_ERROR) from e
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
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions."""
    log_error(
        logger, f"Unhandled exception in {request.method} {request.url.path}", exc, critical=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_code": ErrorCode.INTERNAL_ERROR.value,
            "message": "An unexpected error occurred",
            "details": {"type": type(exc).__name__}
        }
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
