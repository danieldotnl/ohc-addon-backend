from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from ohc_backend.services.ha_service import HomeAssistantService


class TestHomeAssistantService:
    """Tests for HomeAssistantService."""

    @pytest.fixture
    def ha_service(self):
        """Create a test instance of HomeAssistantService with patched session."""
        with patch("aiohttp.ClientSession"):
            service = HomeAssistantService(
                "http://localhost:8123", "test_token")
        return service

    @pytest.mark.asyncio
    async def test_make_request_success(self, ha_service):
        """Test successful API requests."""
        # Define the expected return value
        mock_data = {"key": "value"}

        # Create a complete patch for the request method and context manager
        with patch.object(ha_service, "session") as mock_session:
            # Create a mock response that will be returned by the context manager
            mock_response = MagicMock()
            mock_response.status = status.HTTP_200_OK
            mock_response.ok = True
            mock_response.json = AsyncMock(return_value=mock_data)

            # Configure the async context manager
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_response
            mock_session.request.return_value = mock_cm

            # Call the method
            result = await ha_service.make_request("GET", "http://test/endpoint")

            # Verify results
            assert result == mock_data
            mock_session.request.assert_called_once_with(
                "GET", "http://test/endpoint")

    async def test_close(self, ha_service):
        """Test closing the service."""
        # Create a proper mock session
        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()

        # Replace the service's session with our mock
        ha_service.session = mock_session

        # Call the method
        await ha_service.close()

        # Verify the result
        mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_json_to_yaml(self, ha_service):
        """Test YAML conversion with dict input."""
        dict_input = {"name": "Test", "value": 123}
        yaml_result = ha_service.json_to_yaml(dict_input)

        expected_yaml = "name: Test\nvalue: 123\n"
        assert yaml_result == expected_yaml

    @pytest.mark.asyncio
    async def test_get_automation_content(self, ha_service):
        """Test getting automation content."""
        automation_dict = {"id": "test_auto", "name": "Test Automation"}

        # Patch both methods we'll use
        with patch.object(ha_service, "make_request",
                          new_callable=AsyncMock,
                          return_value=automation_dict) as mock_request, \
            patch.object(ha_service, "json_to_yaml",
                         return_value="name: Test Automation\n") as mock_yaml:

            result = await ha_service.get_automation_content("test_auto")

            mock_request.assert_called_with(
                "GET",
                "http://localhost:8123/api/config/automation/config/test_auto"
            )
            mock_yaml.assert_called_with(automation_dict)
            assert result == "name: Test Automation\n"

    @pytest.mark.asyncio
    async def test_make_request_not_found(self, ha_service):
        """Test 404 response handling."""
        with patch.object(ha_service, "session") as mock_session:
            # Create a mock response
            mock_response = MagicMock()
            mock_response.status = status.HTTP_404_NOT_FOUND

            # Configure the async context manager
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_response
            mock_session.request.return_value = mock_cm

            # Call the method
            result = await ha_service.make_request("GET", "http://test/endpoint")

            # Verify results
            assert result is None
            mock_session.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_make_request_error(self, ha_service):
        """Test error response handling."""
        with patch.object(ha_service, "session") as mock_session:
            # Create a mock response
            mock_response = MagicMock()
            mock_response.status = status.HTTP_500_INTERNAL_SERVER_ERROR
            mock_response.ok = False
            mock_response.json = AsyncMock(
                return_value={"error": "server error"})
            mock_response.raise_for_status = MagicMock(
                side_effect=Exception("HTTP Error"))

            # Configure the async context manager
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_response
            mock_session.request.return_value = mock_cm

            # Call the method and check for exception
            with pytest.raises(Exception):
                await ha_service.make_request("GET", "http://test/endpoint")

    @pytest.mark.asyncio
    async def test_get_script_content(self, ha_service):
        """Test getting script content."""
        script_dict = {"id": "test_script", "name": "Test Script"}

        with patch.object(ha_service, "make_request",
                          new_callable=AsyncMock,
                          return_value=script_dict) as mock_request, \
            patch.object(ha_service, "json_to_yaml",
                         return_value="name: Test Script\n") as mock_yaml:

            result = await ha_service.get_script_content("script.test_script")

            mock_request.assert_called_with(
                "GET",
                "http://localhost:8123/api/config/script/config/test_script"
            )
            mock_yaml.assert_called_with(script_dict)
            assert result == "name: Test Script\n"

    @pytest.mark.asyncio
    async def test_get_automation(self, ha_service):
        """Test getting an automation entity."""
        from ohc_backend.models.ha_entity import Automation

        mock_state = {
            "entity_id": "automation.test_auto",
            "state": "on",
            "attributes": {
                "id": "test_auto",
                "friendly_name": "Test Automation"
            },
            "last_changed": "2023-01-01T00:00:00Z"
        }

        with patch.object(ha_service, "make_request",
                          new_callable=AsyncMock,
                          return_value=mock_state):

            result = await ha_service.get_automation("test_auto")

            assert isinstance(result, Automation)
            assert result.entity_id == "automation.test_auto"
            assert result.state == "on"
            assert result.friendly_name == "Test Automation"
            assert result.automation_id == "test_auto"

    @pytest.mark.asyncio
    async def test_get_script(self, ha_service):
        """Test getting a script entity."""
        from ohc_backend.models.ha_entity import Script

        mock_state = {
            "entity_id": "script.test_script",
            "state": "off",
            "attributes": {
                "friendly_name": "Test Script"
            },
            "last_changed": "2023-01-01T00:00:00Z"
        }

        with patch.object(ha_service, "make_request",
                          new_callable=AsyncMock,
                          return_value=mock_state):

            result = await ha_service.get_script("test_script")

            assert isinstance(result, Script)
            assert result.entity_id == "script.test_script"
            assert result.state == "off"
            assert result.friendly_name == "Test Script"

    @pytest.mark.asyncio
    async def test_get_all_automations_and_scripts(self, ha_service):
        """Test getting all automations and scripts."""
        from ohc_backend.models.ha_entity import Automation, Script

        mock_states = [
            {
                "entity_id": "automation.test_auto",
                "state": "on",
                "attributes": {
                    "id": "test_auto",
                    "friendly_name": "Test Automation"
                },
                "last_changed": "2023-01-01T00:00:00Z"
            },
            {
                "entity_id": "script.test_script",
                "state": "off",
                "attributes": {
                    "friendly_name": "Test Script"
                },
                "last_changed": "2023-01-01T00:00:00Z"
            },
            {
                "entity_id": "light.living_room",  # Should be filtered out
                "state": "on",
                "attributes": {},
                "last_changed": "2023-01-01T00:00:00Z"
            }
        ]

        with patch.object(ha_service, "make_request",
                          new_callable=AsyncMock,
                          return_value=mock_states):

            results = await ha_service.get_all_automations_and_scripts()

            assert len(results) == 2
            assert isinstance(results[0], Automation)
            assert isinstance(results[1], Script)
            assert results[0].entity_id == "automation.test_auto"
            assert results[1].entity_id == "script.test_script"
