"""Sync manager for Home Assistant entities."""

import asyncio
import copy
import logging
from enum import Enum
from typing import cast

from ohc_backend.models.ha_entity import Automation, HAEntity, HAEntityType
from ohc_backend.services.github import GitHubClient
from ohc_backend.services.github.errors import GitHubAPIError, GitHubAuthError, GitHubNotFoundError
from ohc_backend.services.ha_service import HomeAssistantError, HomeAssistantService
from ohc_backend.services.ohc_state import OHCState
from ohc_backend.services.settings import SyncManagerConfig
from ohc_backend.utils.logging import log_error

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
            try:
                state_json = await self.github.content.get_file_contents(self.sync_config.state_file)
                if state_json:
                    logger.info("Loading existing state from GitHub")
                    self._ohc_state = OHCState.from_json(state_json)
            except GitHubNotFoundError:
                # This is expected the first time when a repo is created.
                logger.info(
                    "State file not found on GitHub, starting with empty state")
                # Already using empty state from initialization

            self.status = SyncStatus.RUNNING
            self._task = asyncio.create_task(self._async_loop())
        except Exception as e:
            log_error(logger, "Failed to start sync manager", e)
            self.status = SyncStatus.ERROR
            raise RuntimeError(f"Failed to start sync manager: {e!s}") from e

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
                    log_error(logger, "Error during sync process", e)
                    # Continue running despite errors in a single sync
        except Exception as e:
            log_error(logger, "Fatal error in sync loop", e)
            self.status = SyncStatus.ERROR

    async def run(self) -> None:
        """Run the sync process with improved error handling."""
        try:
            logger.debug("Start syncing changes...")

            # Phase 1: Fetch entities and identify changes
            result = await self._fetch_entities_and_prepare_state()
            if result is None:
                return  # Error occurred during fetch

            ha_entities, state_copy = result

            # Phase 2: Process changes and prepare files
            result = await self._process_changes(ha_entities, state_copy)
            if result is None:
                return  # Error occurred during processing
            files, updated, inserted, deleted = result

            # If nothing changed, we're done
            if not (updated or inserted or deleted):
                logger.info("No entities changed, skipping GitHub commit")
                return
            logger.info(
                "Processed entity changes: %d updated, %d inserted, %d deleted",
                len(updated), len(inserted), len(deleted)
            )

            # Phase 3: Commit changes to GitHub
            success = await self._commit_changes(
                files,
                len(updated),
                len(inserted),
                len(deleted)
            )

            if success:
                # Update the original state only on successful commit
                self._ohc_state = state_copy

        except Exception as e:
            log_error(logger, "Unexpected error in sync process", e)
            self.status = SyncStatus.ERROR

    async def _fetch_entities_and_prepare_state(self) -> tuple[list[HAEntity], OHCState] | None:
        """Fetch entities from Home Assistant and prepare state copy."""
        try:
            ha_entities = await self.ha_service.get_all_automations_and_scripts()
            logger.debug("Retrieved %d entities from Home Assistant",
                         len(ha_entities))

            # Create a deep copy of ohc_state for modifications
            state_copy = OHCState()
            for entity in self._ohc_state.get_entities():
                state_copy.upsert(copy.deepcopy(entity))

        except HomeAssistantError as e:
            log_error(logger, "Failed to fetch entities from Home Assistant", e)
            return None
        else:
            return ha_entities, state_copy

    async def fetch_entity_contents_parallel(self, entities: list[HAEntity]) -> list[tuple[HAEntity, str]]:
        """Fetch content for multiple entities in parallel with controlled concurrency."""
        # Create a semaphore to limit concurrency
        semaphore = asyncio.Semaphore(10)  # Limit to 10 concurrent requests

        async def fetch_with_limit(entity: HAEntity) -> tuple[HAEntity, str]:
            async with semaphore:
                # This ensures only 10 coroutines can execute this block at once
                content = await self._fetch_entity_content(entity)
                return entity, content

        # Create tasks for all entities but they'll be limited by the semaphore
        tasks = [fetch_with_limit(entity) for entity in entities]

        try:
            # If any task fails, this will raise an exception
            results = await asyncio.gather(*tasks)
        except Exception as e:
            log_error(
                logger, "Failed to fetch content for some entities, aborting sync", e)
            # Re-raise to abort the current sync
            raise RuntimeError("Entity content fetch failed") from e
        else:
            return results

    async def _process_changes(
        self,
        ha_entities: list[HAEntity],
        state_copy: OHCState
    ) -> tuple[dict[str, str], list[HAEntity], list[HAEntity], list[HAEntity]] | None:
        """Process entity changes and prepare files for commit."""
        try:
            # First identify potential changes based on metadata
            metadata_updated, inserted, deleted = self._identify_metadata_changes(
                state_copy, ha_entities)

            # Prepare files and collect entities with real changes
            files = {}
            updated = []

            # Process metadata changes in parallel
            entities_to_process = metadata_updated + inserted
            if entities_to_process:
                processed_results = await self.fetch_entity_contents_parallel(entities_to_process)

                for entity, content in processed_results:
                    if content:
                        prefix = "automations" if entity.entity_type == HAEntityType.AUTOMATION else "scripts"
                        files[f"{prefix}/{entity.entity_id}.yaml"] = content
                        updated.append(entity)

            # Check content for timestamp-only changes
            await self._check_content_changes(
                ha_entities,
                state_copy,
                updated,
                files,
                [e.entity_id for e in metadata_updated + inserted + deleted]
            )

            # Only include state file if there are actual entity changes to commit
            if updated or inserted or deleted:
                files[self.sync_config.state_file] = state_copy.to_json()
                logger.debug(
                    "Prepared %d files for commit including state file", len(files))
            elif files:  # We have content changes but no entity metadata changes
                files[self.sync_config.state_file] = state_copy.to_json()
                logger.debug(
                    "Prepared %d files with content changes", len(files))
            else:
                logger.debug("No changes detected, no files to commit")

            return files, updated, inserted, deleted

        except Exception as e:
            log_error(logger, "Error processing entity changes", e)
            return None

    async def _fetch_entity_content(self, entity: HAEntity) -> str | None:
        """Fetch content for a single entity."""
        try:
            if entity.entity_type == HAEntityType.AUTOMATION:
                automation = cast(Automation, entity)
                return await self.ha_service.get_automation_content(automation.automation_id)
            return await self.ha_service.get_script_content(entity.entity_id)
        except Exception as e:
            log_error(
                logger, f"Failed to fetch content for {entity.entity_id}", e)
            return None

    async def _check_content_changes(
        self,
        ha_entities: list[HAEntity],
        state_copy: OHCState,
        updated: list[HAEntity],
        files: dict[str, str],
        already_processed_ids: list[str]
    ) -> None:
        """Check for content changes in entities with only timestamp changes."""
        # Find entities with potential timestamp-only changes
        timestamp_changed_entities = [
            e for e in ha_entities
            if e.entity_id not in already_processed_ids
            and self._ohc_state.get_entity(e.entity_id) is not None
            and e.last_changed != self._ohc_state.get_entity(e.entity_id).last_changed
        ]

        if not timestamp_changed_entities:
            return

        # Process these entities in parallel
        processed_results = await self.fetch_entity_contents_parallel(timestamp_changed_entities)

        for entity, content in processed_results:
            if not content:
                continue

            # Get file path and check if content changed
            prefix = "automations" if entity.entity_type == HAEntityType.AUTOMATION else "scripts"
            file_path = f"{prefix}/{entity.entity_id}.yaml"

            try:
                old_content = await self.github.content.get_file_contents(file_path)

                # If content has changed or doesn't exist in GitHub yet
                if old_content is None or content != old_content:
                    logger.info(
                        "%s has content changes despite only timestamp update", entity.entity_id)
                    files[file_path] = content
                    state_copy.update(entity)
                    updated.append(entity)
            except GitHubNotFoundError:
                # File doesn't exist in GitHub yet
                logger.info("%s does not exist in GitHub yet",
                            entity.entity_id)
                files[file_path] = content
                state_copy.update(entity)
                updated.append(entity)
            except Exception as e:
                log_error(
                    logger, f"Error checking content for {entity.entity_id}", e)

    def _identify_metadata_changes(
        self,
        ohc_state: OHCState,
        new_entities: list[HAEntity],
    ) -> tuple[list[HAEntity], list[HAEntity], list[HAEntity]]:
        """Identify entities with metadata changes (excluding last_changed)."""
        current = ohc_state.get_entities()
        current_by_id = {e.entity_id: e for e in current}
        new_by_id = {e.entity_id: e for e in new_entities}

        updated = []
        inserted = []
        deleted = []

        for entity_id, new_entity in new_by_id.items():
            current = current_by_id.get(entity_id)
            if current:
                # Check if anything besides last_changed has been modified
                metadata_change = (
                    new_entity.friendly_name != current.friendly_name or
                    new_entity.state != current.state or
                    new_entity.is_deleted != current.is_deleted or
                    current.is_deleted  # Always update if it was previously deleted
                )

                if metadata_change:
                    new_entity.is_deleted = False
                    ohc_state.update(new_entity)
                    updated.append(new_entity)
                else:
                    # Only last_changed might be different, update state without marking for commit yet
                    ohc_state.update(new_entity)
            else:
                ohc_state.add(new_entity)
                inserted.append(new_entity)

        for entity_id, current_entity in current_by_id.items():
            if entity_id not in new_by_id and not current_entity.is_deleted:
                current_entity.is_deleted = True
                ohc_state.update(current_entity)
                deleted.append(current_entity)

        return updated, inserted, deleted

    async def _commit_changes(
        self,
        files: dict[str, str],
        updated_count: int,
        inserted_count: int,
        deleted_count: int
    ) -> bool:
        """Commit changes to GitHub."""
        try:
            commit_result = await self.github.content.commit_changed_files(
                files,
                f"Commit {updated_count} updated, {inserted_count} new, {deleted_count} deleted automations and/or scripts."
            )

            if commit_result:
                logger.info(
                    "Successfully committed entities to GitHub: %s", list(files.keys()))
                return True

        except GitHubAuthError as e:
            log_error(logger, "GitHub authentication error", e)
            self.status = SyncStatus.ERROR
            return False
        except GitHubAPIError as e:
            log_error(logger, "GitHub API error", e)
            # Don't change status for temporary API issues
            return False
        except Exception as e:
            log_error(logger, "Unexpected error committing to GitHub", e)
            self.status = SyncStatus.ERROR
            return False
        else:
            logger.info(
                "No changes to commit (GitHub reported files unchanged)")
            return True

    async def update_entities(
        self,
        ohc_state: OHCState,
        new_entities: list[HAEntity],
    ) -> tuple[list[HAEntity], list[HAEntity], list[HAEntity]]:
        """Update entities in the storage."""
        return self._identify_metadata_changes(ohc_state, new_entities)
