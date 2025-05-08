"""Base types and classes for OHC services."""

import logging
from enum import IntEnum, StrEnum, auto
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ohc_backend.errors import AppError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class OHCServiceName(StrEnum):
    """Service name enumeration."""

    SETTINGS = "SETTINGS"
    HOMEASSISTANT = "HOME_ASSISTANT"
    GITHUB = "GITHUB"
    SYNC_MANAGER = "SYNC_MANAGER"


class HealthState(IntEnum):
    """Enumeration of possible service health states."""

    NOT_STARTED = auto()
    STARTED = auto()
    STOPPED = auto()
    ERROR = auto()


class OHCBaseConfig(BaseModel):
    """Base configuration class."""


class OHCBaseService:
    """Base class for OHC services."""

    def __init__(self) -> None:
        """Initialize service with default values."""
        self.report_critical_error_callback: Callable[[OHCServiceName, AppError], Awaitable[None]] | None = None

    def configure(self, config: OHCBaseConfig) -> None:
        """Configure service with settings. Optionally overwrite."""

    async def report_critical_error(self, error: AppError) -> None:
        """Report an error to the orchestrator.

        This method should be called by service implementations when they encounter
        an error they can't handle themselves.
        """
        if self.report_critical_error_callback:
            # Get the service name - you'll need a way to identify which service this is
            service_name = self.get_service_name()  # Implement this method in your class
            await self.report_critical_error_callback(service_name, error)
        else:
            # Fallback logging if error_report_fn isn't set
            logging.error("Error occurred but no error_report_fn is available: %s", error.message)

    def get_service_name(self) -> OHCServiceName:
        """Return the service name for this instance.

        This should be implemented by subclasses to return their specific service name.
        """
        raise NotImplementedError("Subclasses must implement get_service_name()")

    async def start(self) -> None:
        """Start a service."""
        await self._start()

    async def _start(self) -> None:
        """Start the service with actual implementation of service start logic."""
        raise NotImplementedError("_start() method must be implemented by subclasses")

    async def stop(self) -> None:
        """Stop a service."""
        await self._stop()

    async def _stop(self) -> None:
        """Stop the service with actual implementation fo service stop logic."""
        raise NotImplementedError("_stop() method must be implemented by subclasses")
