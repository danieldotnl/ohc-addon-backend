"""Home Assistant Service."""

import json
import logging
from typing import Any

import aiohttp
import yaml
from fastapi import status

from app.models.ha_entity import Automation, HAEntity, Script

logger = logging.getLogger(__name__)


class HomeAssistantBaseError(Exception):
    """Base exception for Home Assistant API errors."""


class HomeAssistantService:
    """Service to interact with Home Assistant."""

    def __init__(self, server_url: str, access_token: str) -> None:
        """Initialize the service."""
        self.server_url = server_url
        self._base_url = f"{server_url}/api"
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {access_token}"})

        logger.info(
            "Home Assistant Service initialized with server_url: %s", server_url)

    async def close(self) -> None:
        """Close the service."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def make_request(self, method: str, url: str, **kwargs: dict) -> Any:  # noqa: ANN401
        """Make an HTTP request and return the JSON response."""
        logger.debug("Making %s request to: %s", method, url)
        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.status == status.HTTP_404_NOT_FOUND:
                    # Return None for 404 instead of raising an exception
                    logger.debug("Resource not found: %s", url)
                    return None

                result = await response.json()

                if not response.ok:
                    logger.error("Home Assistant API error: %s %s",
                                 response.status, result)
                    response.raise_for_status()

                return result
        except aiohttp.ClientError as e:
            logger.debug("Request failed")
            msg = f"Request failed: {e!s}"
            raise HomeAssistantBaseError(
                message=msg, error_type="request_failed") from e

    def json_to_yaml(self, json_content: str) -> str:
        """Convert JSON content to YAML."""
        try:
            # Parse the JSON string to Python dict
            content_dict = json.loads(json_content)
            # Convert the dict to YAML string
            yaml_content = yaml.dump(
                content_dict, default_flow_style=False, sort_keys=False)
        except Exception:
            logger.exception("Error converting json to YAML!")
            raise

        return yaml_content

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
