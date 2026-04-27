"""Tests for the next_open / next_close timestamp sensors."""
from __future__ import annotations

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import DOMAIN


def _entity_id_for(
    hass: HomeAssistant, entry: MockConfigEntry, suffix: str
) -> str:
    """Look up the sensor entity_id by its scoped unique_id."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
    )


async def test_sensor_unique_ids_are_entry_scoped(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Both sensor unique_ids must include the entry_id (multi-instance safe)."""
    registry = er.async_get(hass)
    expected_open = f"{mock_config_entry.entry_id}_next_open"
    expected_close = f"{mock_config_entry.entry_id}_next_close"
    assert registry.async_get_entity_id("sensor", DOMAIN, expected_open) is not None
    assert registry.async_get_entity_id("sensor", DOMAIN, expected_close) is not None


async def test_sensors_have_timestamp_state_when_active(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Both sensors must expose a non-empty timestamp when not paused."""
    open_id = _entity_id_for(hass, mock_config_entry, "next_open")
    close_id = _entity_id_for(hass, mock_config_entry, "next_close")
    open_state = hass.states.get(open_id)
    close_state = hass.states.get(close_id)
    assert open_state is not None and open_state.state not in (None, STATE_UNKNOWN, "")
    assert close_state is not None and close_state.state not in (None, STATE_UNKNOWN, "")


async def test_sensors_become_unknown_when_paused(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """After pausing, both sensors must drop to unknown via the state-update signal."""
    scheduler = setup_integration
    await scheduler.async_set_paused(True)
    await hass.async_block_till_done()

    open_id = _entity_id_for(hass, mock_config_entry, "next_open")
    close_id = _entity_id_for(hass, mock_config_entry, "next_close")
    assert hass.states.get(open_id).state == STATE_UNKNOWN
    assert hass.states.get(close_id).state == STATE_UNKNOWN


async def test_sensors_recover_after_resume(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """After resuming, sensors must come back with valid timestamps."""
    scheduler = setup_integration
    await scheduler.async_set_paused(True)
    await hass.async_block_till_done()
    await scheduler.async_set_paused(False)
    await hass.async_block_till_done()

    open_id = _entity_id_for(hass, mock_config_entry, "next_open")
    assert hass.states.get(open_id).state not in (STATE_UNKNOWN, "", None)
