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
                logger.info("Loading state from GitHub: %s",
                            self.sync_config.state_file)
                state_json = await self.github.content.get_file_contents(self.sync_config.state_file)
                if state_json:
                    logger.info(
                        "Loading existing state from GitHub (length: %d)", len(state_json))
                    self._ohc_state = OHCState.from_json(state_json)
                    logger.info("State loaded with %d entities",
                                len(self._ohc_state.get_entities()))
                else:
                    logger.warning("State file exists but is empty")
            except GitHubNotFoundError:
                # This is expected the first time when a repo is created.
                logger.info(
                    "State file not found on GitHub, starting with empty state")
                # Already using empty state from initialization

            self.status = SyncStatus.RUNNING
            logger.info("Creating sync task and starting async loop")
            self._task = asyncio.create_task(self._async_loop())
            logger.info("Sync task created")
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
            logger.info("Start syncing changes...")

            # Phase 1: Fetch entities and identify changes
            logger.debug("Phase 1: Fetching entities from Home Assistant")
            result = await self._fetch_entities_and_prepare_state()
            if result is None:
                logger.warning("Failed to fetch entities, aborting sync")
                return  # Error occurred during fetch

            ha_entities, state_copy = result
            logger.debug("Phase 1 complete: Retrieved %d entities",
                         len(ha_entities))

            # Phase 2: Process changes and prepare files
            logger.debug("Phase 2: Processing changes")
            result = await self._process_changes(ha_entities, state_copy)
            if result is None:
                logger.warning("Failed to process changes, aborting sync")
                return  # Error occurred during processing

            files, updated, inserted, deleted = result

            # If nothing changed, we're done
            if not (updated or inserted or deleted):
                logger.info("No entities changed, skipping GitHub commit")
                # Still update the internal state to capture last_changed changes
                logger.debug("Updating internal state with %d entities (no content changes)",
                             len(state_copy.get_entities()))
                self._ohc_state = state_copy
                return

            logger.info(
                "Processed entity changes: %d updated, %d inserted, %d deleted",
                len(updated), len(inserted), len(deleted)
            )

            # Phase 3: Commit changes to GitHub
            logger.debug("Phase 3: Committing changes to GitHub")
            success = await self._commit_changes(
                files,
                len(updated),
                len(inserted),
                len(deleted)
            )

            if success:
                # Update the original state only on successful commit
                logger.debug("Updating internal state with %d entities",
                             len(state_copy.get_entities()))
                self._ohc_state = state_copy
                logger.info("Sync completed successfully")

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

            logger.debug("Created state copy with %d entities",
                         len(state_copy.get_entities()))
            return ha_entities, state_copy

        except HomeAssistantError as e:
            log_error(logger, "Failed to fetch entities from Home Assistant", e)
            return None

    async def fetch_entity_contents_parallel(self, entities: list[HAEntity]) -> list[tuple[HAEntity, str]]:
        """Fetch content for multiple entities in parallel with controlled concurrency."""
        if not entities:
            logger.debug("No entities to fetch content for")
            return []

        logger.debug(
            "Fetching content for %d entities in parallel", len(entities))

        # Create a semaphore to limit concurrency
        semaphore = asyncio.Semaphore(
            self.sync_config.ha_max_parallel_requests)

        async def fetch_with_limit(entity: HAEntity) -> tuple[HAEntity, str]:
            async with semaphore:
                # This ensures only limited coroutines can execute this block at once
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
            logger.debug(
                "Successfully fetched content for %d entities", len(results))
            return results

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

    async def _process_changes(
        self,
        ha_entities: list[HAEntity],
        state_copy: OHCState
    ) -> tuple[dict[str, str], list[HAEntity], list[HAEntity], list[HAEntity]] | None:
        """Process entity changes and prepare files for commit."""
        try:
            # Step 1: Identify all potential changes
            potential_changes = await self._identify_potential_changes(ha_entities, state_copy)
            if potential_changes is None:
                return None

            changed_entities, inserted_entities, deleted_entities = potential_changes

            # Step 2: Check content changes and filter timestamp-only updates
            content_changes = await self._check_content_changes(
                changed_entities, inserted_entities, state_copy)
            if content_changes is None:
                return None

            files, final_changed_entities = content_changes

            # Step 3: Prepare final result
            if final_changed_entities or inserted_entities or deleted_entities:
                # Include state file in commit
                files[self.sync_config.state_file] = state_copy.to_json()
                logger.debug(
                    "Prepared %d files for commit including state file", len(files))
            else:
                logger.debug("No changes detected, no files to commit")

            return files, final_changed_entities, inserted_entities, deleted_entities

        except Exception as e:
            log_error(logger, "Error processing entity changes", e)
            return None

    async def _identify_potential_changes(
        self,
        ha_entities: list[HAEntity],
        state_copy: OHCState
    ) -> tuple[list[HAEntity], list[HAEntity], list[HAEntity]] | None:
        """Identify all potential changes (metadata and timestamp changes)."""
        try:
            changed_entities = []
            inserted_entities = []
            deleted_entities = []

            # Find changed and new entities
            for entity in ha_entities:
                current_entity = state_copy.get_entity(entity.entity_id)
                if not current_entity:
                    # New entity
                    logger.debug("New entity detected: %s", entity.entity_id)
                    state_copy.add(entity)
                    inserted_entities.append(entity)
                else:
                    # Check for any changes including last_changed
                    name_changed = entity.friendly_name != current_entity.friendly_name
                    state_changed = entity.state != current_entity.state
                    timestamp_changed = entity.last_changed != current_entity.last_changed
                    deletion_changed = entity.is_deleted != current_entity.is_deleted
                    was_deleted = current_entity.is_deleted

                    if name_changed or state_changed or timestamp_changed or deletion_changed or was_deleted:
                        if was_deleted:
                            entity.is_deleted = False

                        # Log all changes for debugging
                        if name_changed:
                            logger.debug("Name changed for %s: '%s' -> '%s'",
                                         entity.entity_id, current_entity.friendly_name, entity.friendly_name)
                        if state_changed:
                            logger.debug("State changed for %s: '%s' -> '%s'",
                                         entity.entity_id, current_entity.state, entity.state)
                        if timestamp_changed:
                            logger.debug(
                                "Last changed datetime changed for %s", entity.entity_id)
                        if deletion_changed or was_deleted:
                            logger.debug(
                                "Deletion status changed for %s", entity.entity_id)

                        state_copy.update(entity)
                        changed_entities.append(entity)

            # Find deleted entities
            for entity in state_copy.get_entities():
                if (entity.entity_id not in [e.entity_id for e in ha_entities] and
                        not entity.is_deleted):
                    logger.debug("Entity deleted: %s", entity.entity_id)
                    entity.is_deleted = True
                    state_copy.update(entity)
                    deleted_entities.append(entity)

            logger.debug(
                "Potential changes: %d changed, %d new, %d deleted",
                len(changed_entities), len(
                    inserted_entities), len(deleted_entities)
            )

            return changed_entities, inserted_entities, deleted_entities

        except Exception as e:
            log_error(logger, "Error identifying potential changes", e)
            return None

    async def _check_content_changes(
        self,
        changed_entities: list[HAEntity],
        inserted_entities: list[HAEntity],
        state_copy: OHCState
    ) -> tuple[dict[str, str], list[HAEntity]] | None:
        """Check content changes using SHA comparison."""
        try:
            # Prepare a map of file paths to content
            files_map = {}
            entity_map = {}  # Map of file paths to entities
            path_to_entity_id = {}  # Map file paths to entity_ids for lookups

            # Process all changed and new entities
            entities_to_check = changed_entities + inserted_entities

            if not entities_to_check:
                logger.debug("No entities to check for content changes")
                return {}, []

            # Fetch content for all potentially changed entities
            logger.debug("Fetching content for %d entities",
                         len(entities_to_check))
            content_results = await self.fetch_entity_contents_parallel(entities_to_check)

            # Build file map and entity map
            for entity, content in content_results:
                if not content:
                    logger.warning(
                        "Could not get content for %s, skipping", entity.entity_id)
                    continue

                # Get file path
                prefix = "automations" if entity.entity_type == HAEntityType.AUTOMATION else "scripts"
                file_path = f"{prefix}/{entity.entity_id}.yaml"

                files_map[file_path] = content
                entity_map[file_path] = entity
                path_to_entity_id[file_path] = entity.entity_id

            if not files_map:
                logger.debug("No valid content to check")
                return {}, []

            # Use GitHub client's get_changed_files to efficiently determine changes
            changed_files, _, _ = await self.github.content.get_changed_files(files_map)

            # Process results - entities with content changes
            final_changed_entities = []

            for file_path, content in changed_files.items():
                entity = entity_map.get(file_path)
                if entity:
                    if entity in changed_entities:
                        final_changed_entities.append(entity)
                    # If entity in inserted_entities, it's already handled

            # IMPORTANT: Update state for all entities, even those without content changes
            for entity in entities_to_check:
                # Always update the state in state_copy
                state_copy.update(entity)

            logger.info(
                "SHA-based content analysis: %d entities have actual changes",
                len(final_changed_entities)
            )

            # For entities with no content changes, check if metadata changed (not just timestamp)
            for file_path, entity in entity_map.items():
                if file_path not in changed_files and entity in changed_entities:
                    # Content didn't change, but check if metadata did
                    previous_entity = self._ohc_state.get_entity(
                        entity.entity_id)

                    if previous_entity and (
                        entity.friendly_name != previous_entity.friendly_name or
                        entity.state != previous_entity.state or
                        entity.is_deleted != previous_entity.is_deleted
                    ):
                        # Real metadata changes - include in the commit
                        logger.info("Metadata changed (not just timestamp) for %s - adding to commit",
                                    entity.entity_id)
                        changed_files[file_path] = files_map[file_path]
                        final_changed_entities.append(entity)
                    else:
                        # Only timestamp changed - don't include in commit
                        logger.debug(
                            "Only timestamp changed for %s - not adding to commit", entity.entity_id)

            return changed_files, final_changed_entities

        except Exception as e:
            log_error(logger, "Error checking content changes using SHA", e)
            return None

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
