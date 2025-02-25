"""Sync manager for Home Assistant entities."""

import asyncio
import copy
import logging
from enum import Enum
from typing import cast

from app.models.ha_entity import Automation, HAEntity, HAEntityType
from app.services.github import GitHubClient
from app.services.ha_service import HomeAssistantService
from app.services.ohc_state import OHCState
from app.services.settings import SyncManagerConfig

logger = logging.getLogger(__name__)


class SyncStatus(Enum):
    """Home Assistant entity type."""

    RUNNING = "running"
    ERROR = "error"
    SETUP_REQ = "setup required"
    STOPPED = "stopped"


class SetupRequiredError(Exception):
    """Error class for setup required."""


class SyncManager:
    """Sync manager for Home Assistant entities."""

    def __init__(self, ha_service: HomeAssistantService, github: GitHubClient, sync_config: SyncManagerConfig) -> None:
        """Initialize the sync manager."""
        self.ha_service = ha_service
        self.github = github
        self.sync_config = sync_config

        self._ohc_state: OHCState | None = None
        self.status = SyncStatus.STOPPED
        self._task: asyncio.Task | None = None
        self._sleep_task: asyncio.Task | None = None

    def get_ohc_state(self) -> OHCState:
        """Get the ohc state manager."""
        if self.status == SyncStatus.SETUP_REQ:
            raise SetupRequiredError
        if self.status == SyncStatus.ERROR:
            raise RuntimeError
        return self.ohc_state

    async def start(self) -> None:
        """Start the sync manager in a background task."""
        logger.info("Starting sync manager with sync interval %d",
                    self.sync_config.interval)
        self._task = asyncio.create_task(self._async_loop())

    async def stop(self) -> None:
        """Stop the sync manager and cancel any ongoing sleep."""
        logger.info("Stopping sync manager")
        self.status = SyncStatus.STOPPED
        if self._sleep_task and not self._sleep_task.done():
            self._sleep_task.cancel()
        if self._task:
            await self._task

    async def _async_loop(self) -> None:
        """Run the async loop in background."""
        # Prep the ohc state by creating the repo and checking if the state file is available.
        state = await self.github.content.get_file_contents(self.sync_config.state_file)
        self.ohc_state = OHCState.from_json(state) if state else OHCState()
        self.status = SyncStatus.RUNNING

        while self.status == SyncStatus.RUNNING:
            logger.info("Running the loop process")
            await self.run()
            try:
                self._sleep_task = asyncio.create_task(
                    asyncio.sleep(self.sync_config.interval))
                await self._sleep_task
            except asyncio.CancelledError:
                break

    async def run(self) -> None:
        """Run the sync process."""
        try:
            ha_entities = await self.ha_service.get_all_automations_and_scripts()

            # Create a deep copy of ohc_state
            state_copy = OHCState()
            for entity in self.ohc_state.get_entities():
                state_copy.upsert(copy.deepcopy(entity))

            updated, inserted, deleted = await self.update_entities(state_copy, ha_entities)
            logger.info(
                "Synced %d updated, %d inserted, %d deleted entities",
                len(updated),
                len(inserted),
                len(deleted),
            )
        except Exception:
            logger.exception("Error during sync process")
            return

        if len(updated) > 0 or len(inserted) > 0 or len(deleted) > 0:
            try:
                files = {}
                for entity in inserted + updated:
                    if entity.entity_type == HAEntityType.AUTOMATION:
                        automation = cast(Automation, entity)
                        prefix = "automations"
                        content = await self.ha_service.get_automation_content(automation.automation_id)
                    else:
                        prefix = "scripts"
                        content = await self.ha_service.get_script_content(entity.entity_id)

                    filename = f"{prefix}/{entity.entity_id}.yaml"
                    files[filename] = content

            except Exception:
                logger.exception("Error fetching content from Home Assistant")
                raise

            files[self.sync_config.state_file] = state_copy.to_json()

            try:
                commit_result = await self.github.content.commit_changed_files(files, "Update automations and scripts.")
                logger.info("Commit result: %s", commit_result)

                # Only update the original state if GitHub commit was successful
                if commit_result:
                    # Replace the original state with the copy
                    self.ohc_state = state_copy
            except Exception:
                logger.exception("Error committing files to GitHub!")
                self.status = SyncStatus.ERROR
        else:
            logger.info("No automations or scripts have changed.")

    async def update_entities(
        self,
        ohc_state: OHCState,
        new_entities: list[HAEntity],
    ) -> tuple[list[HAEntity], list[HAEntity], list[HAEntity]]:
        """Update entities in the storage."""
        current = ohc_state.get_entities()
        current_by_id = {e.entity_id: e for e in current}
        new_by_id = {e.entity_id: e for e in new_entities}

        updated = []
        inserted = []
        deleted = []

        for entity_id, new_entity in new_by_id.items():
            current = current_by_id.get(entity_id)
            if current:
                # We can compare directly since they're proper typed objects now
                if current.is_deleted or new_entity != current:
                    new_entity.is_deleted = False
                    ohc_state.update(new_entity)
                    updated.append(new_entity)
            else:
                ohc_state.add(new_entity)
                inserted.append(new_entity)

        for entity_id, current_entity in current_by_id.items():
            if entity_id not in new_by_id and not current_entity.is_deleted:
                current_entity.is_deleted = True
                ohc_state.update(current_entity)
                deleted.append(current_entity)

        return updated, inserted, deleted
