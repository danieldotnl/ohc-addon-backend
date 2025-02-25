"""Main FastAPI application file."""

import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.errors import AppError, ErrorCode

from .dependencies import deps
from .routers import automations
from .setup import setup_github


def configure_logging() -> None:
    """Configure the logging."""
    is_dev = os.getenv("ENVIRONMENT") == "dev"

    # Create a custom formatter
    class BetterFormatter(logging.Formatter):
        def formatException(self, exc_info):
            """Format exception without full traceback in production."""
            if is_dev:
                # In development, show full traceback
                return super().formatException(exc_info)
            # In production, show only the error message
            exc_type, exc_value, _ = exc_info
            return f"{exc_type.__name__}: {exc_value}"

    # Format string with colors for better readability
    log_format = (
        "%(asctime)s [%(levelname)8s] %(name)s: %(message)s"
        if not is_dev else
        "%(asctime)s [%(levelname)8s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
    )

    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG if is_dev else logging.INFO,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    # Set formatter for all handlers
    formatter = BetterFormatter(log_format)
    for handler in logging.root.handlers:
        handler.setFormatter(formatter)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.client").setLevel(logging.WARNING)


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
            await setup_github(deps.get_github_client())
        except TimeoutError as err:
            msg = "GitHub authentication timed out. Please restart the add-on to try again."
            logger.exception(msg)
            raise AppError(
                message=msg,
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                error_code=ErrorCode.AUTHENTICATION_FAILED
            ) from err
        except Exception as e:
            msg = "Failed to retrieve GitHub access token"
            logger.exception(msg)
            raise AppError(
                message=msg,
                status_code=status.HTTP_401_UNAUTHORIZED,
                error_code=ErrorCode.AUTHENTICATION_FAILED,
                details={"error": str(e)}
            ) from e

        try:
            logger.info("Starting sync manager")
            sync_manager = deps.get_sync_manager()
            await sync_manager.start()
            logger.info("Application started successfully")
            yield
        except Exception as e:
            logger.exception("Error starting sync manager")
            raise AppError(
                message=f"Sync manager failed to start: {e!s}",
                error_code=ErrorCode.SYNC_ERROR
            ) from e
    except Exception as e:
        if not isinstance(e, AppError):
            logger.exception("Critical startup error")
            msg = "Application failed to start!"
            raise AppError(msg) from e
        raise
    finally:
        logger.info("Cleaning up application resources")
        await deps.cleanup()


app = FastAPI(lifespan=lifespan, debug=os.getenv("ENVIRONMENT") == "dev")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handle application errors."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unhandled exceptions."""
    logger.exception("Unhandled exception")
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
if os.getenv("ENVIRONMENT") != "dev":
    app.mount("/", StaticFiles(directory="../frontend/build",
              html=True), name="frontend")
