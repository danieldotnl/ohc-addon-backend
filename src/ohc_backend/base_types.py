"""Base types and classes for OHC services."""

from enum import IntEnum, StrEnum, auto
from typing import Protocol

from pydantic import BaseModel


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


class HealthMessengerProtocol(Protocol):
    """Protocol for health messenger to avoid circular imports."""

    async def report_health(self, *, is_healthy: bool) -> None:
        """Report health state."""
        ...


class OHCBaseConfig(BaseModel):
    """Base configuration class."""


class OHCBaseService:
    """Base class for OHC services."""

    def __init__(self) -> None:
        """Initialize service with default values."""
        self._health_messenger: HealthMessengerProtocol | None = None

    def configure(self, config: OHCBaseConfig) -> None:
        """Configure service with settings. Optionally overwrite."""

    def set_health_messenger(self, messenger: HealthMessengerProtocol) -> None:
        """Set health messenger."""
        self._health_messenger = messenger

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
