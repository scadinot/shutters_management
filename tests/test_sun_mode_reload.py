"""Tests for sun mode across reloads and removals (v0.9.23).

Before v0.9.23 every unload exited sun mode: reconfiguring any subentry
reloaded the hub and reopened every lowered cover, which were closed
again ~10 min later by the debounce.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.shutters_management.const import DOMAIN

from .conftest import build_hub_with_instance, get_only_subentry_id
from .test_state_persistence import COVER, _seed_storage, _sun_mode_state
from .test_sun_protection import (
    _build_hub_with_sun_protection,
    _set_lux,
    _set_sun,
    _set_temp,
)


async def _setup_in_sun_mode(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> tuple[MockConfigEntry, str]:
    """Set up a sun-protection group already in sun mode, still sunny."""
    _set_sun(hass, azimuth=180, elevation=40)
    _set_lux(hass, 60000)
    _set_temp(hass, 26, "sensor.t_ext")
    entry = _build_hub_with_sun_protection(covers=[COVER])
    subentry_id = get_only_subentry_id(entry)
    _seed_storage(hass_storage, {subentry_id: _sun_mode_state()})

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][subentry_id].is_active is True
    return entry, subentry_id


async def test_reload_keeps_covers_lowered_in_sun_mode(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    entry, subentry_id = await _setup_in_sun_mode(hass, hass_storage)
    manager_before = hass.data[DOMAIN][subentry_id]

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    manager = hass.data[DOMAIN][subentry_id]
    assert manager is not manager_before
    assert manager.is_active is True
    assert cover_calls == []


async def test_removing_sun_protection_subentry_restores_covers(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    entry, subentry_id = await _setup_in_sun_mode(hass, hass_storage)

    assert hass.config_entries.async_remove_subentry(entry, subentry_id)
    await hass.async_block_till_done()

    assert len(cover_calls) == 1
    assert cover_calls[0].data == {"entity_id": COVER, "position": 100}
    assert subentry_id not in hass.data.get(DOMAIN, {})


async def test_disabling_hub_restores_covers(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    entry, _ = await _setup_in_sun_mode(hass, hass_storage)

    assert await hass.config_entries.async_set_disabled_by(
        entry.entry_id, ConfigEntryDisabler.USER
    )
    await hass.async_block_till_done()

    assert len(cover_calls) == 1
    assert cover_calls[0].data == {"entity_id": COVER, "position": 100}


async def test_removing_hub_restores_covers(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    cover_calls = async_mock_service(hass, "cover", "set_cover_position")
    entry, _ = await _setup_in_sun_mode(hass, hass_storage)

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert len(cover_calls) == 1
    assert cover_calls[0].data == {"entity_id": COVER, "position": 100}


async def test_removed_schedule_subentry_is_unscheduled(
    hass: HomeAssistant, base_config
) -> None:
    """A deleted subentry's scheduler must not survive the reload."""
    entry = build_hub_with_instance(instance_data=base_config)
    subentry_id = get_only_subentry_id(entry)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    scheduler = hass.data[DOMAIN][subentry_id]

    with patch.object(
        scheduler, "async_unschedule", wraps=scheduler.async_unschedule
    ) as unschedule:
        assert hass.config_entries.async_remove_subentry(entry, subentry_id)
        await hass.async_block_till_done()

    unschedule.assert_called_once()
    assert subentry_id not in hass.data.get(DOMAIN, {})
