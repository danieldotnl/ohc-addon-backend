"""Dependencies for FastAPI."""

import logging
from typing import cast

from ohc_backend.base_types import OHCServiceName
from ohc_backend.orchestrator import ServiceOrchestrator
from ohc_backend.services.github import GitHubClient
from ohc_backend.services.ha_service import HomeAssistantService
from ohc_backend.services.settings import Settings
from ohc_backend.services.sync_manager import SyncManager

logger = logging.getLogger(__name__)


class DependencyManager:
    """Dependency Manager."""

    def __init__(self) -> None:
        """Initialize dependency manager."""
        self._orchestrator: ServiceOrchestrator | None = None

    @property
    def orchestrator(self) -> ServiceOrchestrator:
        """Get orchestrator."""
        if self._orchestrator is None:
            raise RuntimeError("Orchestrator not initialized")
        return self._orchestrator

    def set_orchestrator(self, orchestrator: ServiceOrchestrator) -> None:
        """Set orchestrator."""
        self._orchestrator = orchestrator

    def get_github_client(self, *, raise_exp: bool = True) -> GitHubClient:
        """Get Github client."""
        if raise_exp:
            self.orchestrator.raise_on_error()

        return cast(GitHubClient, self.orchestrator.get_service(OHCServiceName.GITHUB))

    def get_settings(self, *, raise_exp: bool = True) -> Settings:
        """Get settings manager."""
        if raise_exp:
            self.orchestrator.raise_on_error()

        return cast(Settings, self.orchestrator.get_service(OHCServiceName.SETTINGS))

    def get_ha_service(self, *, raise_exp: bool = True) -> HomeAssistantService:
        """Get Home Assistant Service."""
        if raise_exp:
            self.orchestrator.raise_on_error()

        return cast(HomeAssistantService, self.orchestrator.get_service(OHCServiceName.HOMEASSISTANT))

    def get_sync_manager(self, *, raise_exp: bool = True) -> SyncManager:
        """Get sync manager."""
        if raise_exp:
            self.orchestrator.raise_on_error()

        return cast(SyncManager, self.orchestrator.get_service(OHCServiceName.SYNC_MANAGER))


deps = DependencyManager()

# def get_sync_manager(self) -> SyncManager:
#     """Get sync manager."""
#     if not self._sync_manager:
#         config = self.get_settings().sync_config
#         self._sync_manager = SyncManager(
#             self.get_ha_service(), self.get_github_client(), config)
#     return self._sync_manager

# def get_ohc_state(self) -> OHCState:
#     """Get state manager."""
#     return self.get_sync_manager().get_ohc_state()

# async def clear_github_token(self) -> None:
#     """Clear GitHub token in settings when authentication fails."""
#     if self._settings and self._settings.gh_token:
#         logger.warning(
#             "GitHub authentication failed. Clearing invalid token.")
#         self._settings.gh_config.access_token = None
#         await self._settings.save()

#         # Also update the token in the existing client if it exists
#         if self._github_client:
#             self._github_client.rest_api.set_auth_token("")
