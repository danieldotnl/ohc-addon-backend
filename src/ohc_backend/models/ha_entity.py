"""Home Assistant entity models."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import Enum

from pydantic import BaseModel


class HAEntityType(Enum):
    """Home Assistant entity type."""

    AUTOMATION = "automation"
    SCRIPT = "script"


class HAEntity(BaseModel):
    """Base class for Home Assistant entities."""

    entity_id: str
    state: str
    friendly_name: str
    last_changed: datetime
    is_deleted: bool = False

    @classmethod
    def from_ha_state(cls, data: dict) -> HAEntity:
        """Create an entity from Home Assistant state."""
        entity_id = data["entity_id"]
        if entity_id.startswith("automation."):
            return Automation(
                automation_id=data["attributes"]["id"],
                entity_id=entity_id,
                state=data["state"],
                friendly_name=data["attributes"]["friendly_name"],
                last_changed=data["last_changed"],
            )
        if entity_id.startswith("script."):
            return Script(
                entity_id=entity_id,
                state=data["state"],
                friendly_name=data["attributes"]["friendly_name"],
                last_changed=data["last_changed"],
            )
        msg = f"Invalid entity_id: {entity_id}. Must start with 'automation.' or 'script.'"
        raise ValueError(msg)


class Automation(HAEntity):
    """Automation entity."""

    automation_id: str

    @property
    def entity_type(self) -> HAEntityType:
        """Return the entity type."""
        return HAEntityType.AUTOMATION


class Script(HAEntity):
    """Script entity."""

    @property
    def entity_type(self) -> HAEntityType:
        """Return the entity type."""
        return HAEntityType.SCRIPT
