"""Orchestrator for ohc services."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, cast

from pydantic import BaseModel

from ohc_backend.base_types import OHCBaseConfig, OHCBaseService, OHCServiceName
from ohc_backend.services.settings import Settings
from ohc_backend.utils.logging import log_error

if TYPE_CHECKING:
    from ohc_backend.errors import AppError

logger = logging.getLogger(__name__)


class ServiceState(StrEnum):
    """Enumeration of possible service health states."""

    NOT_STARTED = "NOT_STARTED"
    STARTED = "STARTED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class ServiceInfo(BaseModel):
    """Service related info."""

    model_config = {"arbitrary_types_allowed": True}

    instance: OHCBaseService
    status: ServiceState = ServiceState.NOT_STARTED
    require_config: bool = True


class ServiceOrchestrator:
    """Service orchestrator class."""

    STARTUP_SEQUENCE: ClassVar[list[OHCServiceName]] = [
        OHCServiceName.SETTINGS,
        OHCServiceName.HOMEASSISTANT,
        OHCServiceName.GITHUB,
        OHCServiceName.SYNC_MANAGER,
    ]

    def __init__(self) -> None:
        """Initialize the Orchestrator with service dependencies."""
        self.services: dict[OHCServiceName, ServiceInfo] = {}
        self.error: AppError | None = None

    def register_service(self, name: OHCServiceName, instance: OHCBaseService, *, requires_config: bool = True) -> None:
        """Register services in orchestrator."""
        instance.report_critical_error_callback = self.on_critical_error
        service = ServiceInfo(instance=instance, require_config=requires_config)
        self.services[name] = service

    def raise_on_error(self) -> None:
        """Raise an exception if an error has been reported."""
        if self.error:
            raise self.error

    async def start(self) -> None:
        """Start and configure all registered services."""
        self.error = None
        try:
            for name in self.STARTUP_SEQUENCE:
                info = self.get_service_info(name)
                service = info.instance
                if info.require_config:
                    config = self.get_service_config(name)
                    info.instance.configure(config)
                await service.start()
                info.status = ServiceState.STARTED
                logger.info("%s service has been started", name)
        except Exception as e:  # noqa: BLE001
            log_error(logger, f"Orchestrator failed to start service: {name}.", e, critical=True)
            await self.stop_all_services()

    async def stop_all_services(self) -> None:
        """Stop all services in reverse order of their startup."""
        logger.info("Stopping all services.")
        shutdown_sequence = list(reversed(self.STARTUP_SEQUENCE))
        for service_name in shutdown_sequence:
            try:
                if service_name in self.services:
                    service_info = self.services[service_name]
                    if service_info.status in [ServiceState.STARTED, ServiceState.ERROR]:
                        logger.info("Stopping service: %s", service_name)
                        # Stop the service
                        await service_info.instance.stop()
                        service_info.status = ServiceState.STOPPED
            except Exception as e:  # noqa: BLE001
                log_error(logger, f"Could not stop service {service_name}", e)

    def get_service_config(self, name: OHCServiceName) -> OHCBaseConfig:
        """Return the config for the given service."""
        service = self.get_service(OHCServiceName.SETTINGS)
        settings = cast(Settings, service)
        if not settings:
            raise ValueError("Settings service not found.")
        return settings.get_service_config(name)

    def get_service(self, name: OHCServiceName) -> OHCBaseService:
        """Retrieve a service instance."""
        return self.get_service_info(name).instance

    def get_started_service_or_raise(self, name: OHCServiceName) -> OHCBaseService:
        """Retrieve a service if it is started."""
        info = self.get_service_info(name)
        if not info.status == ServiceState.STARTED:
            raise ValueError(f"Service {name} is not in state 'STARTED'.")
        return info.instance

    def get_service_info(self, name: OHCServiceName) -> ServiceInfo:
        """Retrieve service info."""
        if info := self.services.get(name):
            return info
        raise ValueError(f"Cannot find service {name}.")

    async def on_critical_error(self, service: OHCServiceName, error: AppError) -> None:
        """Report a service error."""
        logger.error(
            "Critical error with code '%s' reported by service %s: %s", error.error_code, service, error.message
        )
        self.error = error
        self.services[service].status = ServiceState.ERROR
        await self.stop_all_services()

    async def stop(self) -> None:
        """Cleanup all running services."""
        await self.stop_all_services()
