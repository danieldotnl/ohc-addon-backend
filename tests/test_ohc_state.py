"""Tests for OHCState class."""

from datetime import datetime

import pytest

from ohc_backend.models.ha_entity import Automation, Script
from ohc_backend.services.ohc_state import OHCState


@pytest.fixture
def ohc_state() -> OHCState:
    """Fixture for creating OHCState."""
    return OHCState()


@pytest.fixture
def automation() -> Automation:
    """Fixture for creating an Automation entity."""
    last_changed_iso = "2025-02-08T19:27:24.580521+00:00"
    return Automation(
        automation_id="234234234234234",
        entity_id="automation.test",
        friendly_name="Test Automation",
        state="on",
        last_changed=datetime.fromisoformat(last_changed_iso),
    )


@pytest.fixture
def script() -> Script:
    """Fixture for creating a Script entity."""
    last_changed_iso = "2025-02-08T19:27:24.580521+00:00"
    return Script(
        entity_id="script.test",
        friendly_name="Test Script",
        state="on",
        last_changed=datetime.fromisoformat(last_changed_iso),
    )


def test_create_entity(ohc_state: OHCState, automation: Automation) -> None:
    """Test creating an entity."""
    entity = ohc_state.add(automation)
    assert entity == automation
    assert ohc_state.get_entity(automation.entity_id) == automation


def test_get_entity(ohc_state: OHCState, automation: Automation) -> None:
    """Test getting an entity."""
    ohc_state.add(automation)
    entity = ohc_state.get_entity(automation.entity_id)
    assert entity == automation


def test_get_automation(ohc_state: OHCState, automation: Automation) -> None:
    """Test getting an automation entity."""
    ohc_state.add(automation)
    entity = ohc_state.get_automation(automation.entity_id)
    assert entity == automation


def test_get_script(ohc_state: OHCState, script: Script) -> None:
    """Test getting a script entity."""
    ohc_state.add(script)
    entity = ohc_state.get_script(script.entity_id)
    assert entity == script


def test_get_automations(ohc_state: OHCState, automation: Automation) -> None:
    """Test getting all automation entities."""
    ohc_state.add(automation)
    automations = ohc_state.get_automations()
    assert automations == [automation]


def test_get_scripts(ohc_state: OHCState, script: Script) -> None:
    """Test getting all script entities."""
    ohc_state.add(script)
    scripts = ohc_state.get_scripts()
    assert scripts == [script]


def test_get_entities(ohc_state: OHCState, automation: Automation, script: Script) -> None:
    """Test getting all entities."""
    ohc_state.add(automation)
    ohc_state.add(script)
    entities = ohc_state.get_entities()
    assert entities == [automation, script]


def test_update_entity(ohc_state: OHCState, automation: Automation) -> None:
    """Test updating an entity."""
    ohc_state.add(automation)
    updated_automation = Automation(
        automation_id="234234234234234",
        entity_id="automation.test",
        friendly_name="Updated Automation",
        state=automation.state,
        last_changed=automation.last_changed,
    )
    entity = ohc_state.update(updated_automation)
    assert entity == updated_automation
    assert ohc_state.get_entity(automation.entity_id) == updated_automation


def test_delete_entity(ohc_state: OHCState, automation: Automation) -> None:
    """Test deleting an entity."""
    ohc_state.add(automation)
    result = ohc_state.remove(automation.entity_id)
    assert result is True
    assert ohc_state.get_entity(automation.entity_id) is None


def test_upsert_entity(ohc_state: OHCState, automation: Automation) -> None:
    """Test upserting an entity."""
    entity = ohc_state.upsert(automation)
    assert entity == automation
    assert ohc_state.get_entity(automation.entity_id) == automation

    updated_automation = Automation(
        automation_id="234234234234234",
        entity_id="automation.test",
        friendly_name="Updated Automation",
        state=automation.state,
        last_changed=automation.last_changed,
    )
    entity = ohc_state.upsert(updated_automation)
    assert entity == updated_automation
    assert ohc_state.get_entity(automation.entity_id) == updated_automation


def test_to_json(ohc_state: OHCState, automation: Automation, script: Script) -> None:
    """Test converting state to JSON."""
    ohc_state.add(automation)
    ohc_state.add(script)
    json_str = ohc_state.to_json()
    assert isinstance(json_str, str)


def test_from_json(ohc_state: OHCState, automation: Automation, script: Script) -> None:
    """Test creating state from JSON."""
    ohc_state.add(automation)
    ohc_state.add(script)
    json_str = ohc_state.to_json()

    new_ohc_state = OHCState.from_json(json_str)
    assert new_ohc_state.get_entity(automation.entity_id) == automation
    assert new_ohc_state.get_entity(script.entity_id) == script
