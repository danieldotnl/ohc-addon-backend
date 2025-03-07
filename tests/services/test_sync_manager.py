import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ohc_backend.models.ha_entity import Automation, HAEntity, Script
from ohc_backend.services.github import GitHubClient
from ohc_backend.services.github.errors import GitHubAPIError, GitHubAuthError, GitHubNotFoundError
from ohc_backend.services.ha_service import HomeAssistantError, HomeAssistantService
from ohc_backend.services.ohc_state import OHCState
from ohc_backend.services.settings import SyncManagerConfig
from ohc_backend.services.sync_manager import SyncManager, SyncStatus


@pytest.fixture
def ha_service():
    """Create a mock HomeAssistantService."""
    return AsyncMock(spec=HomeAssistantService)


@pytest.fixture
def github_client():
    """Create a mock GitHubClient with content manager."""
    client = AsyncMock(spec=GitHubClient)
    client.content = AsyncMock()
    return client


@pytest.fixture
def sync_config():
    """Create a SyncManagerConfig with test settings."""
    return SyncManagerConfig(
        interval=5,  # Short interval for tests
        state_file=".ohcstate/test_state.json",
        ha_max_parallel_requests=5
    )


@pytest.fixture
def sync_manager(ha_service, github_client, sync_config):
    """Create a SyncManager with mock dependencies."""
    manager = SyncManager(ha_service, github_client, sync_config)
    # Ensure the manager is using our mocked client
    assert manager.github is github_client
    return manager


@pytest.fixture
def example_automation():
    """Create an example automation entity."""
    return Automation(
        entity_id="automation.test_automation",
        automation_id="1234",
        friendly_name="Test Automation",
        state="on",
        last_changed="2023-01-01T00:00:00.000000+00:00"
    )


@pytest.fixture
def example_script():
    """Create an example script entity."""
    return Script(
        entity_id="script.test_script",
        friendly_name="Test Script",
        state="off",
        last_changed="2023-01-01T00:00:00.000000+00:00"
    )


@pytest.mark.asyncio
async def test_start_loads_state_from_github(sync_manager, github_client):
    """Test that starting the sync manager loads state from GitHub."""
    # Setup mock for GitHub content
    test_state = OHCState()
    test_automation = Automation(
        entity_id="automation.test_auto",
        automation_id="123",
        friendly_name="Test Auto",
        state="on",
        last_changed="2023-01-01T00:00:00.000000+00:00"
    )
    test_state.add(test_automation)
    state_json = test_state.to_json()

    github_client.content.get_file_contents.return_value = state_json

    # Start the sync manager
    await sync_manager.start()

    # Verify GitHub was called to get state file
    github_client.content.get_file_contents.assert_called_once_with(
        sync_manager.sync_config.state_file
    )

    # Verify state was loaded
    assert len(sync_manager.get_ohc_state().get_entities()) == 1
    assert sync_manager.get_ohc_state().get_entity(
        "automation.test_auto") is not None


@pytest.mark.asyncio
async def test_start_handles_not_found_error(sync_manager, github_client):
    """Test that the sync manager handles state file not found on GitHub."""
    # Setup mock for GitHub content to raise not found error
    github_client.content.get_file_contents.side_effect = GitHubNotFoundError(
        "file", sync_manager.sync_config.state_file)

    # Start the sync manager
    await sync_manager.start()

    # Verify GitHub was called to get state file
    github_client.content.get_file_contents.assert_called_once_with(
        sync_manager.sync_config.state_file
    )

    # Verify empty state was created
    assert len(sync_manager.get_ohc_state().get_entities()) == 0
    assert sync_manager.status == SyncStatus.RUNNING


@pytest.mark.asyncio
async def test_start_handles_auth_error(sync_manager, github_client):
    """Test that the sync manager handles GitHub auth errors."""
    # Setup mock for GitHub content to raise auth error
    github_client.content.get_file_contents.side_effect = GitHubAuthError(
        "Auth failed")

    # Start should raise RuntimeError when auth fails
    with pytest.raises(RuntimeError):
        await sync_manager.start()

    # Verify status is set to ERROR
    assert sync_manager.status == SyncStatus.ERROR


@pytest.mark.asyncio
async def test_stop_cancels_tasks(sync_manager, github_client):
    """Test that stopping the sync manager cancels all tasks."""
    # Configure the mock to return None to simulate file not found
    github_client.content.get_file_contents.return_value = None

    # First start the sync manager
    with patch.object(sync_manager, "_async_loop", return_value=asyncio.Future()):
        await sync_manager.start()

        # Manually create a sleep task for testing
        sync_manager._sleep_task = asyncio.create_task(asyncio.sleep(100))

        # Now stop it
        await sync_manager.stop()

        # Verify sleep task was cancelled
        assert sync_manager._sleep_task.cancelled()
        assert sync_manager.status == SyncStatus.STOPPED


@pytest.mark.asyncio
async def test_fetch_entity_contents_parallel(sync_manager, example_automation, example_script):
    """Test fetching entity contents in parallel with correct concurrency."""
    # Setup _fetch_entity_content to return different content for different entities
    async def mock_fetch_content(entity):
        if entity.entity_id == example_automation.entity_id:
            return "automation: content"
        return "script: content"

    sync_manager._fetch_entity_content = AsyncMock(
        side_effect=mock_fetch_content)

    # Test with multiple entities
    entities = [example_automation, example_script]
    results = await sync_manager.fetch_entity_contents_parallel(entities)

    # Verify results
    assert len(results) == 2
    assert results[0][0] == example_automation
    assert results[0][1] == "automation: content"
    assert results[1][0] == example_script
    assert results[1][1] == "script: content"

    # Verify _fetch_entity_content was called for each entity
    assert sync_manager._fetch_entity_content.call_count == 2


@pytest.mark.asyncio
async def test_fetch_entity_contents_handles_errors(sync_manager, example_automation, example_script):
    """Test fetching entity contents handles errors properly."""
    # Setup _fetch_entity_content to raise an error for one entity
    async def mock_fetch_content(entity):
        if entity.entity_id == example_automation.entity_id:
            raise HomeAssistantError("Failed to fetch")
        return "script: content"

    sync_manager._fetch_entity_content = AsyncMock(
        side_effect=mock_fetch_content)

    # Test with multiple entities should raise RuntimeError
    entities = [example_automation, example_script]
    with pytest.raises(RuntimeError):
        await sync_manager.fetch_entity_contents_parallel(entities)


@pytest.mark.asyncio
async def test_fetch_entity_content(sync_manager, ha_service, example_automation, example_script):
    """Test fetching content for different entity types."""
    # Setup mocks for ha_service
    ha_service.get_automation_content.return_value = "automation yaml"
    ha_service.get_script_content.return_value = "script yaml"

    # Test automation
    content = await sync_manager._fetch_entity_content(example_automation)
    assert content == "automation yaml"
    ha_service.get_automation_content.assert_called_once_with(
        example_automation.automation_id)

    # Test script
    content = await sync_manager._fetch_entity_content(example_script)
    assert content == "script yaml"
    ha_service.get_script_content.assert_called_once_with(
        example_script.entity_id)


@pytest.mark.asyncio
async def test_identify_potential_changes(sync_manager, example_automation):
    """Test identification of potential changes in entities."""
    # Create a state with an existing entity
    state_copy = OHCState()
    existing_automation = Automation(
        entity_id="automation.existing",
        automation_id="existing",
        friendly_name="Existing Automation",
        state="on",
        last_changed="2023-01-01T00:00:00.000000+00:00"
    )
    state_copy.add(existing_automation)

    # Create an updated version of the existing entity
    updated_automation = Automation(
        entity_id="automation.existing",
        automation_id="existing",
        friendly_name="Updated Name",  # Name changed
        state="on",
        last_changed="2023-01-02T00:00:00.000000+00:00"  # Time changed
    )

    # Also add a new entity and an entity to be marked as deleted
    deleted_automation = Automation(
        entity_id="automation.to_delete",
        automation_id="to_delete",
        friendly_name="To Delete",
        state="on",
        last_changed="2023-01-01T00:00:00.000000+00:00"
    )
    state_copy.add(deleted_automation)

    # Entities from HA - includes updated and example but not deleted
    ha_entities = [updated_automation, example_automation]

    # Run the identification process
    result = await sync_manager._identify_potential_changes(ha_entities, state_copy)

    # Unpack results
    changed, inserted, deleted = result

    # Verify results
    assert len(changed) == 1
    assert changed[0].entity_id == "automation.existing"
    assert changed[0].friendly_name == "Updated Name"

    assert len(inserted) == 1
    assert inserted[0].entity_id == example_automation.entity_id

    assert len(deleted) == 1
    assert deleted[0].entity_id == "automation.to_delete"
    assert deleted[0].is_deleted  # Should be marked as deleted


@pytest.mark.asyncio
async def test_check_content_changes(sync_manager, github_client, example_automation):
    """Test checking which entities have actual content changes."""
    # Make sure the sync_manager uses our mocked client
    sync_manager.github = github_client

    # Setup state copy
    state_copy = OHCState()

    # Reset any previous mock configurations
    github_client.content.get_file_contents.reset_mock()

    # Setup GitHub client content methods
    github_client.content.get_file_contents.return_value = "old content"

    # Mock the get_changed_files method which is causing the exception
    changed_files_result = (
        {"automations/automation.test_automation.yaml": "new content"}, None, None)
    github_client.content.get_changed_files = AsyncMock(
        return_value=changed_files_result)

    # Create a parallel fetch result
    content_results = [(example_automation, "new content")]
    sync_manager.fetch_entity_contents_parallel = AsyncMock(
        return_value=content_results)

    # Test with a changed entity
    changed_entities = [example_automation]
    inserted_entities = []

    # Run the method being tested
    result = await sync_manager._check_content_changes(changed_entities, inserted_entities, state_copy)

    # Verify results
    assert result is not None
    files, final_changed = result

    # Verify the correct file was identified as changed
    file_path = f"automations/{example_automation.entity_id}.yaml"
    assert file_path in files
    assert files[file_path] == "new content"
    assert len(final_changed) == 1
    assert final_changed[0] == example_automation


@pytest.mark.asyncio
async def test_process_changes_integration(sync_manager, github_client, example_automation):
    """Test the full process_changes flow integrating all sub-processes."""
    # Setup mock for identifying potential changes
    ha_entities = [example_automation]
    state_copy = OHCState()

    # Setup mocks
    with patch.object(sync_manager, "_identify_potential_changes") as mock_identify:
        # Return a mix of changed, inserted, and deleted entities
        mock_identify.return_value = ([example_automation], [], [])

        # Setup content check mock
        with patch.object(sync_manager, "_check_content_changes") as mock_content:
            # Return files and final changed entities
            test_files = {
                "automations/automation.test_automation.yaml": "content"}
            mock_content.return_value = (test_files, [example_automation])

            # Run process_changes
            result = await sync_manager._process_changes(ha_entities, state_copy)

            # Verify results
            files, updated, inserted, deleted = result
            assert sync_manager.sync_config.state_file in files
            assert "automations/automation.test_automation.yaml" in files
            assert len(updated) == 1
            assert len(inserted) == 0
            assert len(deleted) == 0


@pytest.mark.asyncio
async def test_commit_changes_success(sync_manager, github_client):
    """Test successfully committing changes to GitHub."""
    # Setup mock for commit_changed_files
    github_client.content.commit_changed_files.return_value = True

    # Test files
    files = {
        "automations/test.yaml": "content",
        sync_manager.sync_config.state_file: "{}"
    }

    # Commit the changes
    result = await sync_manager._commit_changes(files, 1, 1, 0)

    # Verify result
    assert result is True
    github_client.content.commit_changed_files.assert_called_once()


@pytest.mark.asyncio
async def test_commit_changes_auth_error(sync_manager, github_client):
    """Test handling auth errors when committing changes."""
    # Setup mock to raise auth error
    github_client.content.commit_changed_files.side_effect = GitHubAuthError(
        "Auth failed")

    # Test files
    files = {"automations/test.yaml": "content"}

    # Commit the changes
    result = await sync_manager._commit_changes(files, 1, 0, 0)

    # Verify result
    assert result is False
    assert sync_manager.status == SyncStatus.ERROR


@pytest.mark.asyncio
async def test_commit_changes_api_error(sync_manager, github_client):
    """Test handling API errors when committing changes."""
    # Set the initial status to RUNNING
    sync_manager.status = SyncStatus.RUNNING

    # Make sure sync_manager is using our mocked client
    sync_manager.github = github_client

    # Setup mock to raise API error
    github_client.content.commit_changed_files.side_effect = GitHubAPIError(
        "API Error", status_code=500)

    # Test files
    files = {"automations/test.yaml": "content"}

    # Commit the changes
    result = await sync_manager._commit_changes(files, 1, 0, 0)

    # Verify result
    assert result is False
    # Status should not change to ERROR for temporary API issues
    assert sync_manager.status == SyncStatus.RUNNING


@pytest.mark.asyncio
async def test_run_integration(sync_manager):
    """Test the full sync run integration."""
    # Setup mocks for all key methods in the run flow
    with patch.object(sync_manager, "_fetch_entities_and_prepare_state") as mock_fetch:
        ha_entities = [MagicMock(spec=HAEntity)]
        state_copy = OHCState()
        mock_fetch.return_value = (ha_entities, state_copy)

        with patch.object(sync_manager, "_process_changes") as mock_process:
            files = {"test.yaml": "content"}
            updated = [MagicMock(spec=HAEntity)]
            inserted = [MagicMock(spec=HAEntity)]
            deleted = []
            mock_process.return_value = (files, updated, inserted, deleted)

            with patch.object(sync_manager, "_commit_changes") as mock_commit:
                mock_commit.return_value = True

                # Run the sync
                await sync_manager.run()

                # Verify all methods were called with expected arguments
                mock_fetch.assert_called_once()
                mock_process.assert_called_once_with(ha_entities, state_copy)
                mock_commit.assert_called_once_with(
                    files, len(updated), len(inserted), len(deleted))

                # State should be updated on successful commit
                assert sync_manager._ohc_state == state_copy


@pytest.mark.asyncio
async def test_run_no_changes(sync_manager):
    """Test sync run when no changes are detected."""
    # Setup mocks for all key methods in the run flow
    with patch.object(sync_manager, "_fetch_entities_and_prepare_state") as mock_fetch:
        ha_entities = [MagicMock(spec=HAEntity)]
        state_copy = OHCState()
        mock_fetch.return_value = (ha_entities, state_copy)

        with patch.object(sync_manager, "_process_changes") as mock_process:
            files = {}  # Empty files dict
            updated = []
            inserted = []
            deleted = []
            mock_process.return_value = (files, updated, inserted, deleted)

            with patch.object(sync_manager, "_commit_changes") as mock_commit:
                # Run the sync
                await sync_manager.run()

                # Process should be called, but commit should not
                mock_process.assert_called_once()
                mock_commit.assert_not_called()

                # State should still be updated even when no files change
                assert sync_manager._ohc_state == state_copy


@pytest.mark.asyncio
async def test_run_fetch_error(sync_manager):
    """Test sync run handling errors during entity fetching."""
    # Setup mock to return None (indicating error)
    with patch.object(sync_manager, "_fetch_entities_and_prepare_state") as mock_fetch:
        mock_fetch.return_value = None

        with patch.object(sync_manager, "_process_changes") as mock_process:
            # Run the sync
            await sync_manager.run()

            # Process should not be called when fetch fails
            mock_process.assert_not_called()


@pytest.mark.asyncio
async def test_async_loop_handles_cancellation(sync_manager):
    """Test that async loop handles task cancellation properly."""
    # Mock the run method
    sync_manager.run = AsyncMock()

    # Set status to running so the loop will execute
    sync_manager.status = SyncStatus.RUNNING

    # Create a controlled way to exit the loop
    async def mock_sleep(seconds):
        # First call will raise CancelledError to simulate cancellation
        sync_manager.status = SyncStatus.STOPPED
        raise asyncio.CancelledError()

    # Patch the sleep function to cause cancellation
    with patch("asyncio.sleep", mock_sleep):
        # Run the loop - it should exit when mock_sleep raises CancelledError
        await sync_manager._async_loop()

        # Verify run was called once
        sync_manager.run.assert_called_once()


@pytest.mark.asyncio
async def test_async_loop_handles_exceptions(sync_manager):
    """Test that async loop handles exceptions during run()."""
    # Track run count
    run_count = 0

    # Override the run method to raise an exception but also exit the loop
    async def mock_run():
        nonlocal run_count
        run_count += 1
        # After first call, set status to exit the loop
        if run_count >= 1:
            sync_manager.status = SyncStatus.STOPPED
        # Always raise an exception
        raise Exception("Test error")

    # Replace the run method
    sync_manager.run = mock_run

    # Set initial status to running
    sync_manager.status = SyncStatus.RUNNING

    # Run the loop
    await sync_manager._async_loop()

    # Verify the run method was called at least once
    assert run_count >= 1
    # Verify status is now stopped
    assert sync_manager.status == SyncStatus.STOPPED
