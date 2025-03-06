"""Dependencies for FastAPI."""

import logging
import os

from ohc_backend.services.github import GitHubClient
from ohc_backend.services.ha_service import HomeAssistantService
from ohc_backend.services.ohc_state import OHCState
from ohc_backend.services.settings import Settings
from ohc_backend.services.sync_manager import SyncManager

logger = logging.getLogger(__name__)


class DependencyManager:
    """Dependency Manager."""

    def __init__(self, settings_path: str) -> None:
        """Initialize dependency manager."""
        self._settings_path: str = settings_path
        self._settings: Settings | None = None
        self._github_client: GitHubClient | None = None
        self._sync_manager: SyncManager | None = None
        self._home_assistant_service: HomeAssistantService | None = None

    async def async_init(self) -> None:
        """Async initializer."""
        logger.info("Initializing setting from path: %s", self._settings_path)
        self._settings = Settings(self._settings_path)
        await self._settings.async_init()

    async def cleanup(self) -> None:
        """Cleanup dependency resources."""
        if self._sync_manager:
            await self._sync_manager.stop()

        if self._github_client:
            await self._github_client.close()

        if self._home_assistant_service:
            await self._home_assistant_service.close()

    def get_github_client(self) -> GitHubClient:
        """Get Github client."""
        if not self._github_client:
            api_url = self.get_settings().gh_config.api_url
            client_id = self.get_settings().gh_config.client_id
            token = self.get_settings().gh_token
            self._github_client = GitHubClient(
                api_url=api_url, client_id=client_id, access_token=token)
        return self._github_client

    def get_settings(self) -> Settings:
        """Get settings manager."""
        return self._settings

    def get_ha_service(self) -> HomeAssistantService:
        """Get Home Assistant Service."""
        if not self._home_assistant_service:
            settings = self.get_settings()
            server = settings.ha_config.server
            token = settings.ha_config.token
            self._home_assistant_service = HomeAssistantService(server, token)
        return self._home_assistant_service

    def get_sync_manager(self) -> SyncManager:
        """Get sync manager."""
        if not self._sync_manager:
            config = self.get_settings().sync_config
            self._sync_manager = SyncManager(
                self.get_ha_service(), self.get_github_client(), config)
        return self._sync_manager

    def get_ohc_state(self) -> OHCState:
        """Get state manager."""
        return self.get_sync_manager().get_ohc_state()

    async def clear_github_token(self) -> None:
        """Clear GitHub token in settings when authentication fails."""
        if self._settings and self._settings.gh_token:
            logger.warning(
                "GitHub authentication failed. Clearing invalid token.")
            self._settings.gh_config.access_token = None
            await self._settings.save()

            # Also update the token in the existing client if it exists
            if self._github_client:
                self._github_client.rest_api.set_auth_token("")

    async def setup_github(self) -> None:
        """Start the github auth flow and create repo if required."""
        settings = self.get_settings()
        client = self.get_github_client()
        if not settings.gh_token:
            scope = settings.gh_config.scope
            token = await client.authenticate(scope)
            settings.gh_config.access_token = token
            await settings.save()
            client.rest_api.set_auth_token(token)

        await client.init_repository(settings.gh_config.repo_request)


data_folder = os.getenv("HA_DATA_FOLDER", "/data")
deps = DependencyManager(f"{data_folder}/config.json")
