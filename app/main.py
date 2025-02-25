"""Main FastAPI application file."""

import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
    await deps.async_init()
    try:
        await setup_github(deps.get_github_client())
    except TimeoutError as err:
        msg = "GitHub authentication timed out. Please restart the add-on to try again."
        logger.exception(msg)
        raise RuntimeError(msg) from err
    except Exception as e:
        msg = "Failed to retrieve GitHub access token. Please restart the add-on to try again."
        logger.exception(msg, exc_info=e)
        raise RuntimeError(msg) from e

    try:
        sync_manager = deps.get_sync_manager()
        await sync_manager.start()
        yield
    finally:
        await deps.cleanup()


app = FastAPI(lifespan=lifespan, debug=os.getenv("ENVIRONMENT") == "dev")


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
