"""Home Assistant Service."""

import logging
from typing import cast
from urllib.parse import urlparse

import aiohttp
import yaml
from fastapi import status

from ohc_backend.base_types import OHCServiceName
from ohc_backend.models.ha_entity import Automation, HAEntity, Script
from ohc_backend.orchestrator import OHCBaseService
from ohc_backend.services.settings import HAConfig, OHCBaseConfig
from ohc_backend.utils.logging import log_error

logger = logging.getLogger(__name__)


class HomeAssistantError(Exception):
    """Base exception for Home Assistant API errors."""

    def __init__(self, message: str, status_code: int | None = None, error_type: str = "ha_error") -> None:
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


class HomeAssistantService(OHCBaseService):
    """Service to interact with Home Assistant."""

    def __init__(
        self,
    ) -> None:
        """Initialize the service."""
        self._base_url: str | None = None
        self.timeout: aiohttp.ClientTimeout | None = None
        self.session: aiohttp.ClientSession | None = None
        self.access_token: str | None = None

    def get_service_name(self) -> OHCServiceName:
        """Return the service name for this instance."""
        return OHCServiceName.HOMEASSISTANT

    async def _start(self) -> None:
        """Start the service."""
        if self.access_token is None or self.access_token == "":
            raise ValueError("Access token is required when starting the Home Assistant service.")
        if not self.is_valid_url(self._base_url):
            raise ValueError("A valid base url is required when starting the Home Assistant service.")
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.access_token}"}, timeout=self.timeout
            )

    def configure(self, config: OHCBaseConfig) -> None:
        """Configure home assistant service."""
        ha_config = cast(HAConfig, config)
        self._base_url = f"{ha_config.server}/api"
        self.access_token = ha_config.token
        self.timeout = aiohttp.ClientTimeout(total=15)

        logger.debug("Home Assistant Service configured with server_url: %s", ha_config.server)

    def is_valid_url(self, url: str | None) -> bool:
        """Check if the provided string is a valid URL."""
        if url is None:
            return False

        try:
            result = urlparse(url.strip())
            # Check for scheme (http, https) and netloc (domain)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    async def _stop(self) -> None:
        """Close the service."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
        logger.debug("Home Assistant service stopped.")

    async def make_request(self, method: str, url: str, **kwargs: dict) -> dict | str | None:
        """Make an HTTP request and return the JSON response with improved error handling."""
        logger.debug("Making %s request to: %s", method, url)

        # Extract resource info from URL for better error messages
        path_parts = url.split("/")
        resource_type = path_parts[-2] if len(path_parts) >= 2 else "resource"  # noqa: PLR2004
        resource_id = path_parts[-1] if path_parts else "unknown"

        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.status == status.HTTP_404_NOT_FOUND:
                    logger.debug("%s not found: %s", resource_type, resource_id)
                    return None

                if response.status == status.HTTP_401_UNAUTHORIZED:
                    error_text = await response.text()
                    logger.error("Home Assistant authentication error: %s", error_text)
                    msg = f"Authentication failed: {error_text}"
                    raise HomeAssistantAuthError(  # noqa: TRY301
                        msg
                    )

                try:
                    result = await response.json()
                except aiohttp.ContentTypeError as err:
                    content = await response.text()
                    if not response.ok:
                        logger.exception("Invalid JSON response from HA API: %s %s", response.status, content[:200])
                        msg = f"Invalid JSON response from Home Assistant (Status: {response.status})"
                        raise HomeAssistantError(msg, status_code=response.status) from err
                    return content  # Return text content if not JSON

                if not response.ok:
                    error_msg = result.get("message", str(result)) if isinstance(result, dict) else str(result)
                    logger.error("Home Assistant API error: %s %s", response.status, error_msg)
                    msg = f"Home Assistant API error: {error_msg}"
                    raise HomeAssistantError(  # noqa: TRY301
                        msg, status_code=response.status
                    )

                return result
        except aiohttp.ClientConnectorError as e:
            log_error(logger, "Cannot connect to Home Assistant", e)
            raise HomeAssistantConnectionError("Cannot connect to Home Assistant") from e
        except aiohttp.ClientError as e:
            log_error(logger, "Home Assistant request failed", e)
            raise HomeAssistantError("Request failed", error_type="request_failed") from e
        except HomeAssistantError:
            raise
        except Exception as e:
            log_error(logger, "Unexpected error in Home Assistant request", e)
            raise HomeAssistantError("Unexpected error") from e

    def json_to_yaml(self, content: dict) -> str:
        """Convert JSON content to YAML."""
        try:
            # Convert the dict to YAML string
            return yaml.dump(content, default_flow_style=False, sort_keys=False)
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
        return Automation.from_ha_state(
            await self.make_request("GET", f"{self._base_url}/states/automation.{automation_id}")
        )

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
