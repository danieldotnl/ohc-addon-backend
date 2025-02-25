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
    # StreamHandler for the console
    stream_handler = logging.StreamHandler(sys.stdout)

    logging.basicConfig(
        format=(
            "%(asctime)s [%(processName)s: %(process)d]\
                 [%(threadName)s: %(thread)d] [%(levelname)s] %(name)s: %(message)s"
        ),
        level=logging.DEBUG if os.getenv(
            "ENVIRONMENT") == "dev" else logging.INFO,
        handlers=[
            stream_handler,
        ],
    )


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
