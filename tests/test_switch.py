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


def _switch_entity_id(
    hass: HomeAssistant, entry: MockConfigEntry
) -> str:
    """Look up the switch entity_id by its scoped unique_id."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_simulation_active"
    )


async def test_switch_unique_id_is_entry_scoped(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """The switch unique_id must include the entry_id (multi-instance safe)."""
    expected = f"{mock_config_entry.entry_id}_simulation_active"
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("switch", DOMAIN, expected) is not None


async def test_switch_initial_state_is_on(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """At startup the simulation is active, so the switch is on."""
    entity_id = _switch_entity_id(hass, mock_config_entry)
    assert hass.states.get(entity_id).state == STATE_ON


async def test_switch_turn_off_pauses_scheduler(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Turning the switch off must pause the scheduler and reflect off."""
    scheduler = setup_integration
    entity_id = _switch_entity_id(hass, mock_config_entry)

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
    entity_id = _switch_entity_id(hass, mock_config_entry)

    await scheduler.async_set_paused(True)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_OFF

    await hass.services.async_call(
        "switch", SERVICE_TURN_ON, {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert scheduler.paused is False
    assert hass.states.get(entity_id).state == STATE_ON
