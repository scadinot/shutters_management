"""Tests for the next_open / next_close timestamp sensors."""
from __future__ import annotations

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shutters_management.const import (
    DOMAIN,
    SUBENTRY_TYPE_PRESENCE_SIM,
)

from .conftest import build_hub_with_instance, get_only_subentry_id


def _entity_id_for(
    hass: HomeAssistant, subentry_id: str, suffix: str
) -> str:
    """Look up the sensor entity_id by its subentry-scoped unique_id."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{subentry_id}_{suffix}"
    )
    assert entity_id is not None, f"Missing sensor entity for suffix: {suffix}"
    return entity_id


async def test_sensor_unique_ids_are_subentry_scoped(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Both sensor unique_ids must include the subentry_id (multi-instance safe)."""
    registry = er.async_get(hass)
    subentry_id = get_only_subentry_id(mock_config_entry)
    expected_open = f"{subentry_id}_next_open"
    expected_close = f"{subentry_id}_next_close"
    assert registry.async_get_entity_id("sensor", DOMAIN, expected_open) is not None
    assert registry.async_get_entity_id("sensor", DOMAIN, expected_close) is not None


async def test_sensor_entity_ids_are_stable_english(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Resolved entity_ids must use the English slug regardless of locale."""
    registry = er.async_get(hass)
    subentry_id = get_only_subentry_id(mock_config_entry)
    open_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{subentry_id}_next_open"
    )
    close_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{subentry_id}_next_close"
    )
    assert open_id == "sensor.bureau_next_open"
    assert close_id == "sensor.bureau_next_close"


async def test_sensors_have_timestamp_state_when_active(
    hass: HomeAssistant, setup_integration, mock_config_entry: MockConfigEntry
) -> None:
    """Both sensors must expose a non-empty timestamp when not paused."""
    subentry_id = get_only_subentry_id(mock_config_entry)
    open_id = _entity_id_for(hass, subentry_id, "next_open")
    close_id = _entity_id_for(hass, subentry_id, "next_close")
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

    subentry_id = get_only_subentry_id(mock_config_entry)
    open_id = _entity_id_for(hass, subentry_id, "next_open")
    close_id = _entity_id_for(hass, subentry_id, "next_close")
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

    subentry_id = get_only_subentry_id(mock_config_entry)
    open_id = _entity_id_for(hass, subentry_id, "next_open")
    assert hass.states.get(open_id).state not in (STATE_UNKNOWN, "", None)


async def test_presence_simulation_sensors_use_dedicated_device(
    hass: HomeAssistant, base_config
) -> None:
    """A presence_simulation subentry must produce next-trigger sensors on its own device.

    Covers the ``SUBENTRY_TYPE_PRESENCE_SIM`` branch in ``sensor.py`` setup
    and confirms the platform picks the ``presence_simulation``
    device-translation_key (not the default ``instance``).
    """
    entry = build_hub_with_instance(
        instance_data=base_config,
        instance_title="Présence",
        instance_unique_id="presence",
        subentry_type=SUBENTRY_TYPE_PRESENCE_SIM,
        entry_id="presence_sensor_entry",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    subentry_id = get_only_subentry_id(entry)
    entity_registry = er.async_get(hass)
    open_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{subentry_id}_next_open"
    )
    close_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{subentry_id}_next_close"
    )
    assert open_id is not None and close_id is not None

    device_registry = dr.async_get(hass)
    open_entry = entity_registry.async_get(open_id)
    device = device_registry.async_get(open_entry.device_id)
    assert device is not None
    assert (DOMAIN, subentry_id) in device.identifiers

    component = hass.data["entity_components"]["sensor"]
    open_entity = component.get_entity(open_id)
    close_entity = component.get_entity(close_id)
    assert open_entity is not None and close_entity is not None
    assert open_entity.device_info["translation_key"] == "presence_simulation"
    assert close_entity.device_info["translation_key"] == "presence_simulation"
