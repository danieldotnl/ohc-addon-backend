"""Sync manager for Home Assistant entities."""

import asyncio
import copy
import logging
from enum import Enum
from typing import cast

from app.models.ha_entity import Automation, HAEntity, HAEntityType
from app.services.github import GitHubClient
from app.services.github.errors import GitHubAPIError, GitHubAuthError
from app.services.ha_service import HomeAssistantError, HomeAssistantService
from app.services.ohc_state import OHCState
from app.services.settings import SyncManagerConfig

logger = logging.getLogger(__name__)


class SyncStatus(Enum):
    """Sync manager status."""

    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"


class SyncManager:
    """Sync manager for Home Assistant entities."""

    def __init__(self, ha_service: HomeAssistantService, github: GitHubClient, sync_config: SyncManagerConfig) -> None:
        """Initialize the sync manager."""
        self.ha_service = ha_service
        self.github = github
        self.sync_config = sync_config

        self._ohc_state: OHCState = OHCState()
        self.status = SyncStatus.STOPPED
        self._task: asyncio.Task | None = None
        self._sleep_task: asyncio.Task | None = None

    def get_ohc_state(self) -> OHCState:
        """Get the ohc state manager."""
        if self.status == SyncStatus.ERROR:
            logger.error("Sync manager is in error state, cannot access state")
            msg = "Sync manager is in error state"
            raise RuntimeError(msg)
        return self._ohc_state

    async def start(self) -> None:
        """Start the sync manager in a background task."""
        if self.status != SyncStatus.STOPPED:
            logger.warning("Sync manager already running or in error state")
            return

        logger.info("Starting sync manager with sync interval %d seconds",
                    self.sync_config.interval)
        try:
            # First load state from GitHub if available
            state_json = await self.github.content.get_file_contents(self.sync_config.state_file)
            if state_json:
                logger.info("Loading existing state from GitHub")
                self._ohc_state = OHCState.from_json(state_json)
            else:
                logger.info(
                    "No existing state found, starting with empty state")

            self.status = SyncStatus.RUNNING
            self._task = asyncio.create_task(self._async_loop())
        except Exception as e:
            logger.exception("Failed to start sync manager: %s", str(e))
            self.status = SyncStatus.ERROR
            raise RuntimeError(
                f"Failed to start sync manager: {e!s}") from e

    async def stop(self) -> None:
        """Stop the sync manager and cancel any ongoing sleep."""
        logger.info("Stopping sync manager")
        self.status = SyncStatus.STOPPED
        if self._sleep_task and not self._sleep_task.done():
            self._sleep_task.cancel()
        if self._task and not self._task.done():
            await self._task

    async def _async_loop(self) -> None:
        """Run the async loop in background."""
        try:
            while self.status == SyncStatus.RUNNING:
                logger.info("Running sync process")
                try:
                    await self.run()

                    # Sleep until next sync
                    try:
                        self._sleep_task = asyncio.create_task(
                            asyncio.sleep(self.sync_config.interval))
                        await self._sleep_task
                    except asyncio.CancelledError:
                        logger.info("Sleep interrupted, stopping sync loop")
                        break
                except Exception as e:
                    logger.exception("Error during sync process: %s", str(e))
                    # Continue running despite errors in a single sync
        except Exception as e:
            logger.exception("Fatal error in sync loop: %s", str(e))
            self.status = SyncStatus.ERROR

    async def run(self) -> None:
        """Run the sync process with improved error handling."""
        try:
            logger.info("Starting sync process")

            # Phase 1: Fetch entities from Home Assistant
            try:
                ha_entities = await self.ha_service.get_all_automations_and_scripts()
                logger.info("Retrieved %d entities from Home Assistant",
                            len(ha_entities))
            except HomeAssistantError:
                logger.exception(
                    "Failed to fetch entities from Home Assistant!")
                return  # Exit early but don't change status

            # Create a deep copy of ohc_state for modifications
            state_copy = OHCState()
            for entity in self._ohc_state.get_entities():
                state_copy.upsert(copy.deepcopy(entity))

            # Phase 2: Process entity changes
            try:
                updated, inserted, deleted = await self.update_entities(state_copy, ha_entities)
                logger.info(
                    "Processed entity changes: %d updated, %d inserted, %d deleted",
                    len(updated),
                    len(inserted),
                    len(deleted),
                )
            except Exception as e:
                logger.exception("Error processing entity changes: %s", str(e))
                return

            # If nothing changed, we're done
            if not (updated or inserted or deleted):
                logger.info("No entities changed, skipping GitHub commit")
                return

            # Phase 3: Fetch content for changed entities
            try:
                files = {}
                for entity in inserted + updated:
                    try:
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
                        logger.exception("Failed to fetch content for %s",
                                         entity.entity_id)
                        # Abort the entire commit process if any entity fails
                        logger.warning(
                            "Aborting commit due to failure fetching entity content")
                        return  # Exit without committing anything

                # Add state file
                files[self.sync_config.state_file] = state_copy.to_json()
                logger.info("Prepared %d files for commit", len(files))

            except Exception as e:
                logger.exception(
                    "Error fetching content from Home Assistant: %s", str(e))
                return

            # Phase 4: Commit changes to GitHub
            try:
                commit_result = await self.github.content.commit_changed_files(
                    files, f"Commit {len(updated)} updated, {len(inserted)} new, {len(deleted)} deleted automations and/or scripts."
                )

                if commit_result:
                    logger.info(
                        "Successfully committed changes to GitHub: %s", commit_result.sha)
                    # Update the original state only on successful commit
                    self.ohc_state = state_copy
                else:
                    logger.info(
                        "No changes to commit (GitHub reported files unchanged)")

            except GitHubAuthError:
                logger.exception("GitHub authentication error!")
                self.status = SyncStatus.ERROR
            except GitHubAPIError:
                logger.exception("GitHub API error!")
                # Don't change status for temporary API issues
            except Exception:
                logger.exception(
                    "Unexpected error committing to GitHub!")
                self.status = SyncStatus.ERROR

        except Exception:
            logger.exception("Unexpected error in sync process!")
            # We only set ERROR for truly unexpected exceptions in the overall process
            # This will stop the sync loop
            self.status = SyncStatus.ERROR

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
