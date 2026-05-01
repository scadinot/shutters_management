"""Tests for the simulation_active switch entity."""
from __future__ import annotations

from homeassistant.const import (
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import DOMAIN

from .conftest import get_only_subentry_id


def _switch_entity_id(hass: HomeAssistant, subentry_id: str) -> str:
    """Look up the switch entity_id by its subentry-scoped unique_id."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "switch", DOMAIN, f"{subentry_id}_simulation_active"
    )
    assert entity_id is not None, "simulation_active switch entity was not created"
    return entity_id


async def test_switch_unique_id_is_subentry_scoped(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """The switch unique_id must include the subentry_id (multi-instance safe)."""
    subentry_id = get_only_subentry_id(mock_config_entry)
    expected = f"{subentry_id}_simulation_active"
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("switch", DOMAIN, expected) is not None


async def test_switch_entity_id_is_stable_english(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Resolved entity_id must use the English slug regardless of locale."""
    registry = er.async_get(hass)
    subentry_id = get_only_subentry_id(mock_config_entry)
    entity_id = registry.async_get_entity_id(
        "switch", DOMAIN, f"{subentry_id}_simulation_active"
    )
    assert entity_id == "switch.bureau_simulation_active"


async def test_switch_initial_state_is_on(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """At startup the simulation is active, so the switch is on."""
    subentry_id = get_only_subentry_id(mock_config_entry)
    entity_id = _switch_entity_id(hass, subentry_id)
    assert hass.states.get(entity_id).state == STATE_ON


async def test_switch_turn_off_pauses_scheduler(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Turning the switch off must pause the scheduler and reflect off."""
    scheduler = setup_integration
    subentry_id = get_only_subentry_id(mock_config_entry)
    entity_id = _switch_entity_id(hass, subentry_id)

    await hass.services.async_call(
        "switch", SERVICE_TURN_OFF, {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert scheduler.paused is True
    assert hass.states.get(entity_id).state == STATE_OFF


async def test_switch_turn_on_resumes_scheduler(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Turning the switch on must resume the scheduler and reflect on."""
    scheduler = setup_integration
    subentry_id = get_only_subentry_id(mock_config_entry)
    entity_id = _switch_entity_id(hass, subentry_id)

    await scheduler.async_set_paused(True)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_OFF

    await hass.services.async_call(
        "switch", SERVICE_TURN_ON, {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert scheduler.paused is False
    assert hass.states.get(entity_id).state == STATE_ON
