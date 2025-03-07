"""Home Assistant Service."""

import logging
from typing import Any

import aiohttp
import yaml
from fastapi import status

from ohc_backend.models.ha_entity import Automation, HAEntity, Script

logger = logging.getLogger(__name__)


class HomeAssistantError(Exception):
    """Base exception for Home Assistant API errors."""

    def __init__(self, message: str, status_code: int = None, error_type: str = "ha_error") -> None:
        """Initialize the error."""
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        super().__init__(message)


class HomeAssistantAuthError(HomeAssistantError):
    """Authentication error with Home Assistant."""

    def __init__(self, message: str = "Authentication with Home Assistant failed") -> None:
        """Initialize the error."""
        super().__init__(message, status_code=401, error_type="ha_auth_error")


class HomeAssistantConnectionError(HomeAssistantError):
    """Connection error with Home Assistant."""

    def __init__(self, message: str = "Could not connect to Home Assistant") -> None:
        """Initialize the error."""
        super().__init__(message, status_code=503, error_type="ha_connection_error")


class HomeAssistantResourceNotFoundError(HomeAssistantError):
    """Resource not found in Home Assistant."""

    def __init__(self, resource_type: str, resource_id: str) -> None:
        """Initialize the error."""
        message = f"{resource_type} not found: {resource_id}"
        super().__init__(message, status_code=404, error_type="ha_not_found")
        self.resource_type = resource_type
        self.resource_id = resource_id


class HomeAssistantService:
    """Service to interact with Home Assistant."""

    def __init__(self, server_url: str, access_token: str, session: aiohttp.ClientSession | None = None,
                 timeout: aiohttp.ClientTimeout | None = None) -> None:
        """Initialize the service."""
        self.server_url = server_url
        self._base_url = f"{server_url}/api"
        self.timeout = timeout or aiohttp.ClientTimeout(total=15)
        self.session = session or aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=self.timeout)

        logger.info(
            "Home Assistant Service initialized with server_url: %s", server_url)

    async def close(self) -> None:
        """Close the service."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def make_request(self, method: str, url: str, **kwargs: dict) -> Any:
        """Make an HTTP request and return the JSON response with improved error handling."""
        logger.debug("Making %s request to: %s", method, url)

        # Extract resource info from URL for better error messages
        path_parts = url.split("/")
        resource_type = path_parts[-2] if len(path_parts) >= 2 else "resource"
        resource_id = path_parts[-1] if path_parts else "unknown"

        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.status == status.HTTP_404_NOT_FOUND:
                    logger.debug("%s not found: %s",
                                 resource_type, resource_id)
                    return None

                if response.status == status.HTTP_401_UNAUTHORIZED:
                    error_text = await response.text()
                    logger.error(
                        "Home Assistant authentication error: %s", error_text)
                    msg = f"Authentication failed: {error_text}"
                    raise HomeAssistantAuthError(  # noqa: TRY301
                        msg)

                try:
                    result = await response.json()
                except aiohttp.ContentTypeError as err:
                    content = await response.text()
                    if not response.ok:
                        logger.exception("Invalid JSON response from HA API: %s %s",
                                         response.status, content[:200])
                        msg = f"Invalid JSON response from Home Assistant (Status: {response.status})"
                        raise HomeAssistantError(
                            msg,
                            status_code=response.status
                        ) from err
                    return content  # Return text content if not JSON

                if not response.ok:
                    error_msg = result.get("message", str(result)) if isinstance(
                        result, dict) else str(result)
                    logger.error("Home Assistant API error: %s %s",
                                 response.status, error_msg)
                    msg = f"Home Assistant API error: {error_msg}"
                    raise HomeAssistantError(  # noqa: TRY301
                        msg,
                        status_code=response.status
                    )

                return result
        except aiohttp.ClientConnectorError as e:
            logger.error("Cannot connect to Home Assistant: %s", str(e))
            raise HomeAssistantConnectionError(
                f"Cannot connect to Home Assistant: {e!s}")
        except aiohttp.ClientError as e:
            logger.error("Home Assistant request failed: %s", str(e))
            raise HomeAssistantError(
                f"Request failed: {e!s}", error_type="request_failed")
        except HomeAssistantError:
            raise
        except Exception as e:
            logger.exception("Unexpected error in Home Assistant request")
            raise HomeAssistantError(f"Unexpected error: {e!s}")

    def json_to_yaml(self, content: dict) -> str:
        """Convert JSON content to YAML."""
        try:
            # Convert the dict to YAML string
            return yaml.dump(
                content, default_flow_style=False, sort_keys=False)
        except Exception:
            logger.exception("Error converting json to YAML!")
            raise

    async def get_automation_content(self, automation_id: str) -> str:
        """Get the content of an automation from Home Assistant."""
        json_content = await self.make_request("GET", f"{self._base_url}/config/automation/config/{automation_id}")
        return self.json_to_yaml(json_content)

    async def get_script_content(self, entity_id: str) -> str:
        """Get the content of a script from Home Assistant."""
        name = entity_id.split(".")[1]
        json_content = await self.make_request("GET", f"{self._base_url}/config/script/config/{name}")
        return self.json_to_yaml(json_content)

    async def get_automation(self, automation_id: str) -> Automation:
        """Get a single automation from Home Assistant."""
        return Automation.from_ha_state(await self.make_request("GET",
                                                                f"{self._base_url}/states/automation.{automation_id}"))

    async def get_script(self, script_id: str) -> Script:
        """Get a single automation from Home Assistant."""
        return Script.from_ha_state(await self.make_request("GET", f"{self._base_url}/states/script.{script_id}"))

    async def get_all_automations_and_scripts(self) -> list[HAEntity]:
        """Get both automations and scripts from Home Assistant."""
        states = await self.make_request("GET", f"{self._base_url}/states")

        entities = []

        for state in states:
            entity_id = state["entity_id"]
            if entity_id.startswith(("automation.", "script.")):
                entities.append(HAEntity.from_ha_state(state))
        return entities
