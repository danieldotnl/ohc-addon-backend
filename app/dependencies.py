"""Dependencies for FastAPI."""

import logging
import os

from app.services.github import GitHubClient
from app.services.home_assistant_service import HomeAssistantService
from app.services.ohc_state import OHCState
from app.services.settings import Settings
from app.services.sync_manager import SyncManager

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
        if self._github_client:
            await self._github_client.close()

        if self._sync_manager:
            await self._sync_manager.stop()

        if self._home_assistant_service:
            await self._home_assistant_service.close()

    def get_github_client(self) -> GitHubClient:
        """Get Github client."""
        if not self._github_client:
            api_url = self.get_settings().gh_config.api_url
            client_id = self.get_settings().gh_config.client_id
            token = self.get_settings().gh_token
            self._github_client = GitHubClient(api_url=api_url, client_id=client_id, access_token=token)
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
            self._sync_manager = SyncManager(self.get_ha_service(), self.get_github_client(), config)
        return self._sync_manager

    def get_ohc_state(self) -> OHCState:
        """Get state manager."""
        return self.get_sync_manager().get_ohc_state()


data_folder = os.getenv("HA_DATA_FOLDER", "./data")
deps = DependencyManager(f"{data_folder}/config.json")
